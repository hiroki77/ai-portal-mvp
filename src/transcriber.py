import os,re,json,time,base64,logging,shutil
from pathlib import Path
from dataclasses import dataclass,asdict
from typing import List,Tuple
import numpy as np
try:
    import cv2
except ImportError:
    cv2=None
try:
    import whisper
except ImportError:
    whisper=None
try:
    from google import genai
    from google.genai import types as gtypes
except ImportError:
    genai=None;gtypes=None
try:
    import easyocr
except ImportError:
    easyocr=None
from src.utils import run_ffmpeg,get_video_resolution,get_video_duration
from src.cost_tracker import get_tracker
logger=logging.getLogger(__name__)
FI=0.1

@dataclass
class SubtitleEntry:
    start:float;end:float;text:str;speaker:str;style:str;confidence:float=1.0
    def to_dict(self):return asdict(self)

class SubtitleRecognizer:
    DIFF_TH=12.0
    BRIGHT_TH=140

    def __init__(self,config):
        tc=config["transcription"]
        self.wm=tc["whisper_model"];self.lang=tc["language"]
        self.ocr_engine=tc.get("ocr_engine","gemini")
        self.srr=tc["subtitle_region_ratio"]
        self.bs=tc.get("batch_size",4)
        self.mr=tc.get("max_retries",3)
        self.td=config["paths"]["temp_dir"]
        self._g=None;self._gm=tc.get("gemini_model","gemini-2.0-flash")
        gk=tc.get("gemini_api_key","") or os.environ.get("GEMINI_API_KEY","")
        if gk and genai:self._g=genai.Client(api_key=gk)
        self._wm=None;self._or=None

    def recognize(self,vp):
        logger.info(f"OCR 0.1s: {vp}")
        ws=self._whisper(vp)
        logger.info(f"Whisper:{len(ws)}")
        if self.ocr_engine=="gemini" and self._g:
            os_=self._smart_ocr(vp)
        else:
            os_=self._easyocr(vp)
        logger.info(f"OCR:{len(os_)}")
        merged=self._cross_validate(ws,os_)
        logger.info(f"CrossValidated:{len(merged)}")
        return merged

    def _smart_ocr(self,vp):
        w,h=get_video_resolution(vp);sy=int(h*(1-self.srr));sh=h-sy
        fd=os.path.join(self.td,"f01")
        os.makedirs(fd,exist_ok=True)
        try:
            run_ffmpeg(["-i",str(vp),"-vf",f"fps=10,crop=iw:{sh}:0:{sy}",
                        "-q:v","2",os.path.join(fd,"f_%07d.jpg")],timeout=1800)
            ff=sorted(Path(fd).glob("f_*.jpg"))
            if not ff:return []
            logger.info(f"{len(ff)} frames")
            cp=self._detect(ff)
            logger.info(f"{len(cp)} changes")
            if not cp:return []
            oc=self._ocr_cp(cp,ff)
            return self._build(oc)
        finally:
            shutil.rmtree(fd,ignore_errors=True)

    def _detect(self,ff):
        ch=[];pg=None;pt=False
        for i,fp in enumerate(ff):
            f=cv2.imread(str(fp))
            if f is None:continue
            g=cv2.cvtColor(f,cv2.COLOR_BGR2GRAY)
            br=np.sum(g>self.BRIGHT_TH)/g.size
            ht=0.003<br<0.45
            if pg is not None:
                d=np.mean(cv2.absdiff(g,pg))
                if d>self.DIFF_TH:ch.append((i,str(fp)))
                elif ht!=pt:ch.append((i,str(fp)))
            elif ht:
                ch.append((i,str(fp)))
            pg=g;pt=ht
        return ch

    def _ocr_cp(self,cp,af):
        res=[]
        for bi in range(0,len(cp),self.bs):
            b=cp[bi:bi+self.bs];ps=[c[1] for c in b];ix=[c[0] for c in b]
            ts=[i*FI for i in ix]
            oc=self._gbr(ps,ts)
            res.extend([(ix[j],ts[j],oc[j][1],oc[j][2],oc[j][3]) for j in range(len(oc))])
            if bi+self.bs<len(cp):time.sleep(4.5)
        return res

    def _build(self,oc):
        if not oc:return []
        ent=[]
        for i,(idx,ts,tx,sp,sy) in enumerate(oc):
            if not tx:continue
            st=ts
            en=oc[i+1][1] if i+1<len(oc) else ts+2.0
            if ent and ent[-1].text==tx:
                ent[-1].end=round(en,1);continue
            ent.append(SubtitleEntry(start=round(st,1),end=round(en,1),
                text=tx,speaker=sp,style=sy,confidence=0.95))
        return ent

    def _gbr(self,ps,ts):
        for a in range(self.mr):
            try:return self._gb(ps,ts)
            except Exception as e:
                logger.warning(f"OCR err({a+1}):{e}")
                if a<self.mr-1:time.sleep(2**(a+1))
                else:return [(t,"","unknown","normal") for t in ts]

    def _gb(self,ps,ts):
        prompt=(
            "あなたは最高精度のOCRエンジンです。"
            "以下の画像はYouTube動画の字幕(テロップ)部分です。\n\n"
            "【ルール】\n"
            "- 全ての文字を1文字たりとも間違えず正確に読む\n"
            "- 句読点、感嘆符、括弧も正確に\n"
            "- テキストがない画像は空文字を返す\n"
            "- テキストの色: pink(ピンク系)、cyan(シアン/水色系)、other\n"
            "- 文字サイズが大きい場合はemphasis、それ以外はnormal\n"
            "- 画像の枚数と同じ数の要素を必ず返す\n\n"
            "JSON配列のみ出力:\n"
            '[{"text":"正確なテキスト","color":"pink/cyan/other","style":"normal/emphasis"},...]'
        )
        pa=[gtypes.Part.from_text(prompt)]
        for fp in ps:
            with open(fp,"rb") as f:
                pa.append(gtypes.Part.from_bytes(data=f.read(),mime_type="image/jpeg"))
        r=self._g.models.generate_content(
            model=self._gm,
            contents=gtypes.Content(parts=pa,role="user"),
            config=gtypes.GenerateContentConfig(temperature=0,max_output_tokens=1500))
        get_tracker().record_gemini(f'OCR ({len(ps)}枚)', self._gm, r)
        m=re.search(r'\[.*\]',r.text.strip(),re.DOTALL)
        if not m:return [(t,"","unknown","normal") for t in ts]
        it=json.loads(m.group());res=[]
        for i,t in enumerate(ts):
            if i<len(it):
                x=it[i];tx=x.get("text","").strip()
                co=x.get("color","other").lower()
                sy=x.get("style","normal").lower()
                sp="aya" if "pink" in co else("junpei" if "cyan" in co else "unknown")
                res.append((t,tx,sp,sy))
            else:res.append((t,"","unknown","normal"))
        return res

    def _cross_validate(self,whisper_segs,ocr_segs):
        if not ocr_segs:return whisper_segs
        if not whisper_segs:return ocr_segs
        validated=[]
        for oc in ocr_segs:
            best_w=None;best_ov=0
            for ws in whisper_segs:
                ov_s=max(oc.start,ws.start);ov_e=min(oc.end,ws.end)
                if ov_e>ov_s:
                    ov=ov_e-ov_s
                    if ov>best_ov:best_ov=ov;best_w=ws
            if best_w and best_ov>0.2:
                oc_clean=re.sub(r'[\s　、。、！？.,!?]','',oc.text)
                ws_clean=re.sub(r'[\s　、。、！？.,!?]','',best_w.text)
                sim=self._similarity(oc_clean,ws_clean)
                if sim<0.3 and len(ws_clean)>3:
                    oc.text=best_w.text;oc.confidence=0.7
                else:
                    oc.confidence=min(1.0,0.8+sim*0.2)
            validated.append(oc)
        for ws in whisper_segs:
            covered=any(min(ws.end,o.end)-max(ws.start,o.start)>0.3 for o in ocr_segs)
            if not covered and ws.text.strip():validated.append(ws)
        validated.sort(key=lambda e:e.start)
        cleaned=[]
        for e in validated:
            if not e.text.strip() or e.end-e.start<0.2:continue
            e.text=re.sub(r'\s+',' ',e.text).strip()
            if cleaned and cleaned[-1].text==e.text and abs(cleaned[-1].start-e.start)<0.3:
                if(e.end-e.start)>(cleaned[-1].end-cleaned[-1].start):cleaned[-1]=e
                continue
            cleaned.append(e)
        return cleaned

    def _similarity(self,a,b):
        if not a or not b:return 0.0
        sa,sb=set(a),set(b)
        inter=len(sa&sb);union=len(sa|sb)
        return inter/union if union else 0.0

    def _whisper(self,vp):
        au=os.path.join(self.td,"a.wav")
        run_ffmpeg(["-i",str(vp),"-vn","-acodec","pcm_s16le","-ar","16000","-ac","1",au])
        try:
            if self._wm is None:self._wm=whisper.load_model(self.wm)
            r=self._wm.transcribe(au,language=self.lang,word_timestamps=True,verbose=False)
            return[SubtitleEntry(start=x["start"],end=x["end"],text=x["text"].strip(),
                speaker="unknown",style="normal") for x in r.get("segments",[]) if x["text"].strip()]
        finally:
            if os.path.exists(au):os.remove(au)

    def _easyocr(self,vp):
        if not cv2 or not easyocr:return []
        w,h=get_video_resolution(vp);sy=int(h*(1-self.srr))
        fd=os.path.join(self.td,"foc");os.makedirs(fd,exist_ok=True)
        try:
            run_ffmpeg(["-i",str(vp),"-vf",f"fps=10,crop=iw:{h-sy}:0:{sy}",
                        "-q:v","2",os.path.join(fd,"f_%07d.jpg")],timeout=1800)
            if self._or is None:self._or=easyocr.Reader(["ja","en"],gpu=False)
            pg=None;raw=[]
            for i,fp in enumerate(sorted(Path(fd).glob("f_*.jpg"))):
                ts=i*FI;f=cv2.imread(str(fp))
                if f is None:continue
                g=cv2.cvtColor(f,cv2.COLOR_BGR2GRAY)
                if pg is not None and np.mean(cv2.absdiff(g,pg))<12:pg=g;continue
                pg=g
                if not(0.003<np.sum(g>140)/g.size<0.45):raw.append((ts,"","unknown","normal"));continue
                r=self._or.readtext(str(fp),detail=1,paragraph=True)
                tx="".join(d[1] for d in r if len(d)>=2).strip() if r else ""
                hsv=cv2.cvtColor(f,cv2.COLOR_BGR2HSV)
                pk=np.sum(cv2.inRange(hsv,np.array([140,50,150]),np.array([175,255,255]))>0)
                cy=np.sum(cv2.inRange(hsv,np.array([80,50,150]),np.array([100,255,255]))>0)
                sp="aya" if pk>cy and pk>100 else("junpei" if cy>100 else "unknown")
                raw.append((ts,tx,sp,"normal"))
            return self._grp(raw)
        finally:shutil.rmtree(fd,ignore_errors=True)

    def _grp(self,raw):
        ent=[];ct,cs,cy,st,en="","unknown","normal",0.0,0.0
        for ts,tx,sp,sy in raw:
            if tx==ct and tx:en=ts+FI
            else:
                if ct:ent.append(SubtitleEntry(start=round(st,1),end=round(en,1),
                    text=ct,speaker=cs,style=cy,confidence=0.95))
                ct,cs,cy,st,en=tx,sp,sy,ts,ts+FI
        if ct:ent.append(SubtitleEntry(start=round(st,1),end=round(en,1),
            text=ct,speaker=cs,style=cy,confidence=0.95))
        return ent
