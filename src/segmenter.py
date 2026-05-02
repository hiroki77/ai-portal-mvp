import os,re,json,time,logging
from dataclasses import dataclass
logger=logging.getLogger(__name__)
try:
    from google import genai
    from google.genai import types as gtypes
except ImportError:
    genai=None;gtypes=None

@dataclass
class ClipSegment:
    start:float;end:float;subtitles:list;score:float=0.0
    topic_summary:str="";reason:str="";punchline:str=""
    @property
    def duration(s):return s.end-s.start

class TopicSegmenter:
    TB=["で","でさ","というわけで","次","じゃあ","ところで","ちなみに","あと","それで","最後に"]
    VW=["やばい","マジ","笑","可愛い","無理","神","最高","おもろい","怖い","泣く","エモい"]

    def __init__(s,config):
        s.mn=config["clips"]["min_duration"]
        s.mx=config["clips"]["max_duration"]
        s.cc=config["clips"]["count"]
        tc=config["transcription"];s._g=None
        s._gm=tc.get("gemini_model","gemini-2.0-flash")
        gk=tc.get("gemini_api_key","") or os.environ.get("GEMINI_API_KEY","")
        if gk and genai:s._g=genai.Client(api_key=gk)

    def select_clips(s,subs,video_path,pref=None,audio_features=None):
        if not subs:return []
        # 音声特徴を抽出(笑い・音量変化)
        af=audio_features or s._extract_audio_features(video_path)
        if s._g:
            c=s._gem(subs,pref,af)
            if c:return c
            logger.warning("Gemini失敗,fallback")
        return s._rules(subs,pref)

    def _extract_audio_features(s,video_path):
        """FFmpegで音量変化を検出し、盛り上がりポイントを返す"""
        try:
            import subprocess
            # 音量レベルを取得 (1秒ごと)
            result=subprocess.run(
                ["ffmpeg","-i",str(video_path),"-af",
                 "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level",
                 "-f","null","-"],
                capture_output=True,text=True,timeout=300)
            # RMSレベルをパース
            levels=[];times=[]
            for line in result.stderr.split("\n"):
                if "RMS_level" in line:
                    m=re.search(r'RMS_level=(-?[\d.]+)',line)
                    if m:
                        lv=float(m.group(1))
                        levels.append(lv)
                elif "pts_time:" in line:
                    m=re.search(r'pts_time:([\d.]+)',line)
                    if m:times.append(float(m.group(1)))
            if not levels:return {"peaks":[],"loud_sections":[]}
            import numpy as np
            arr=np.array(levels)
            mean_lv=np.mean(arr);std_lv=np.std(arr)
            # 平均より1.5σ以上大きい箇所 = 盛り上がり
            peaks=[]
            for i,lv in enumerate(levels):
                if lv>mean_lv+1.5*std_lv:
                    t=times[i] if i<len(times) else i*1.0
                    peaks.append({"time":round(t,1),"level":round(lv,1)})
            # 連続して音量が高い区間 = 笑い/リアクション
            loud=[]
            if peaks:
                seg_start=peaks[0]["time"]
                prev_t=peaks[0]["time"]
                for p in peaks[1:]:
                    if p["time"]-prev_t>3.0:
                        loud.append({"start":round(seg_start,1),"end":round(prev_t+1,1)})
                        seg_start=p["time"]
                    prev_t=p["time"]
                loud.append({"start":round(seg_start,1),"end":round(prev_t+1,1)})
            return {"peaks":peaks[:20],"loud_sections":loud[:10]}
        except Exception as e:
            logger.debug(f"audio features skip: {e}")
            return {"peaks":[],"loud_sections":[]}

    def _gem(s,subs,pref=None,af=None):
        lines=[f"[{x.start:.1f}-{x.end:.1f}] {{'aya':'綾','junpei':'純平'}.get(x.speaker,'?')}: {x.text}" for x in subs]
        tr="\n".join(lines)
        boost=""
        if pref:
            kw=pref.get("boost_keywords",[])
            if kw:boost+=f"\n過去バズキーワード:{",".join(kw)}"
            pd=pref.get("preferred_duration",0)
            if pd:boost+=f"\n過去バズ平均:{pd}s"
        # 音声特徴情報
        audio_info=""
        if af and af.get("loud_sections"):
            ls=", ".join(f"{x['start']}-{x['end']}s" for x in af["loud_sections"])
            audio_info=f"\n\n【音声分析】盛り上がり区間(笑い・リアクションが大きい):{ls}\nこれらの区間を含むクリップを優先的に選んでください。"

        pr=(
            "あなたはプロの切り抜き動画クリエイターです。"
            "以下は中町兄妹(YouTube)の全字幕です。\n\n"
            f"{tr}\n\n"
            f"「それだけ見ても面白い」切り抜きを3本作ります。\n"
            f"【絶対条件】\n- {s.mn}-{s.mx}秒\n"
            "- 話の途中で絶対に切らない\n- 3本重複なし\n\n"
            "【オチの定義 - 最重要】\n"
            "切り抜きはオチが全て。以下のいずれかで終わる:\n"
            "- 笑い: ツッコミ、ボケ、予想外の展開\n"
            "- 感動: 兄妹愛、良い話\n"
            "- 驚き: 衡撃告白、予想外の事実\n"
            "- 共感: 「わかる～」な日常\n"
            "オチなしはNG\n\n"
            "【構成】フリ(導入)→展開→オチ\n"
            "【優先】兄妹の掛け合い、リアクション大、SNSシェア向き"
            f"{boost}{audio_info}\n\n"
            "JSON配列のみ出力。\n"
            '[{"start":秒,"end":秒,"topic":"","punchline":"オチ","reason":"","score":1-10},...]'
        )
        for a in range(3):
            try:
                r=s._g.models.generate_content(
                    model=s._gm,
                    contents=gtypes.Content(parts=[gtypes.Part.from_text(pr)],role="user"),
                    config=gtypes.GenerateContentConfig(temperature=0.3,max_output_tokens=2000))
                m_=re.search(r'\[.*\]',r.text.strip(),re.DOTALL)
                if not m_:continue
                it=json.loads(m_.group());cl=[]
                for x in it[:s.cc]:
                    st,en=float(x["start"]),float(x["end"])
                    if en-st<s.mn:en=st+s.mn
                    if en-st>s.mx:en=st+s.mx
                    cs=[sub for sub in subs if sub.start>=st and sub.end<=en]
                    cl.append(ClipSegment(start=st,end=en,subtitles=cs,
                        score=float(x.get("score",5)),
                        topic_summary=x.get("topic",""),
                        punchline=x.get("punchline",""),
                        reason=x.get("reason","")))
                if cl:
                    for i,c in enumerate(cl):
                        logger.info(f"  Clip{i+1}:{c.start:.0f}-{c.end:.0f}s({c.duration:.0f}s) "
                                    f"「{c.topic_summary}」 オチ:{c.punchline}")
                    return cl
            except Exception as e:
                logger.warning(f"Gemini err({a+1}):{e}")
                if a<2:time.sleep(2**a)
        return []

    def _rules(s,subs,pref=None):
        b=[0]
        for i in range(1,len(subs)):
            if subs[i].start-subs[i-1].end>2.0:b.append(i);continue
            for w in s.TB:
                if subs[i].text.startswith(w):b.append(i);break
        b.append(len(subs));b=sorted(set(b));ca=[]
        for i in range(len(b)-1):
            for j in range(i+1,len(b)):
                sl=subs[b[i]:b[j]]
                if not sl:continue
                d=sl[-1].end-sl[0].start
                if s.mn<=d<=s.mx:
                    ca.append(ClipSegment(start=sl[0].start,end=sl[-1].end,subtitles=sl))
                if d>s.mx:break
        for c in ca:
            tx=" ".join(x.text for x in c.subtitles)
            sc=sum(3.0 for w in s.VW if w in tx)
            sc+=sum(2.0 for i in range(1,len(c.subtitles))
                   if c.subtitles[i].speaker!=c.subtitles[i-1].speaker
                   and c.subtitles[i].speaker!="unknown")
            if 30<=c.duration<=45:sc+=5.0
            c.score=sc;c.topic_summary=tx[:50]
        ca.sort(key=lambda c:c.score,reverse=True);se=[]
        for c in ca:
            if not any(not(c.end<=x.start or c.start>=x.end) for x in se):se.append(c)
            if len(se)>=s.cc:break
        return se
