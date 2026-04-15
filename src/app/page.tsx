import Link from "next/link";

const STEPS = [
  { icon: "📍", title: "場所を入力", desc: "今いる場所を入力するだけ" },
  { icon: "⏰", title: "時間を選ぶ", desc: "1時間〜3時間から選択" },
  { icon: "🏨", title: "ホテルを選ぶ", desc: "近くの空き部屋を自動検索" },
  { icon: "🚕", title: "タクシーでお迎え", desc: "寝て起きたら元の場所へ" },
];

const PRICES = [
  { duration: "1時間", price: "¥3,700〜", note: "サクッと回復" },
  { duration: "2時間", price: "¥5,500〜", note: "おすすめ" },
  { duration: "3時間", price: "¥7,000〜", note: "しっかり休息" },
];

export default function LandingPage() {
  return (
    <main className="flex-1 flex flex-col">
      {/* Hero */}
      <section className="relative bg-gradient-to-br from-primary via-secondary to-primary-dark px-6 pt-16 pb-20 text-white text-center">
        <div className="animate-slide-up">
          <p className="text-sm font-medium tracking-widest uppercase opacity-80 mb-4">
            NapGO
          </p>
          <h1 className="text-4xl font-bold leading-tight mb-4">
            疲れたら、
            <br />
            すぐナップ。
          </h1>
          <p className="text-white/80 text-base leading-relaxed mb-8">
            タクシーがお迎え → ホテルで仮眠 → 元の場所にお届け
            <br />
            すべてワンタップで完結。
          </p>
          <Link
            href="/booking"
            className="inline-block bg-white text-primary font-bold text-lg px-8 py-4 rounded-2xl shadow-lg hover:shadow-xl transition-all active:scale-95"
          >
            今すぐ予約する
          </Link>
        </div>
      </section>

      {/* How it works */}
      <section className="px-6 py-12">
        <h2 className="text-xl font-bold text-center mb-8">使い方はカンタン</h2>
        <div className="space-y-4">
          {STEPS.map((step, i) => (
            <div
              key={i}
              className="flex items-start gap-4 bg-white rounded-xl p-4 shadow-sm"
            >
              <div className="flex-shrink-0 w-12 h-12 bg-primary/10 rounded-xl flex items-center justify-center text-2xl">
                {step.icon}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-bold text-primary bg-primary/10 rounded-full w-5 h-5 flex items-center justify-center">
                    {i + 1}
                  </span>
                  <h3 className="font-bold text-base">{step.title}</h3>
                </div>
                <p className="text-sm text-text-light">{step.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing */}
      <section className="px-6 py-12 bg-white">
        <h2 className="text-xl font-bold text-center mb-2">料金プラン</h2>
        <p className="text-sm text-text-light text-center mb-8">
          ホテル代 + タクシー往復込み
        </p>
        <div className="grid grid-cols-3 gap-3">
          {PRICES.map((p, i) => (
            <div
              key={i}
              className={`rounded-xl p-4 text-center border-2 transition-all ${
                i === 1
                  ? "border-primary bg-primary/5 scale-105"
                  : "border-border bg-white"
              }`}
            >
              <p className="text-sm font-medium text-text-light mb-1">
                {p.duration}
              </p>
              <p className="text-lg font-bold text-primary">{p.price}</p>
              {i === 1 ? (
                <span className="inline-block mt-2 text-xs font-bold text-white bg-primary rounded-full px-2 py-0.5">
                  {p.note}
                </span>
              ) : (
                <p className="mt-2 text-xs text-text-light">{p.note}</p>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="px-6 py-12 text-center">
        <h2 className="text-xl font-bold mb-3">さあ、休もう。</h2>
        <p className="text-sm text-text-light mb-6">
          最短5分でタクシーがお迎えに。
        </p>
        <Link
          href="/booking"
          className="inline-block bg-primary text-white font-bold text-base px-8 py-4 rounded-2xl shadow-lg hover:bg-primary-dark transition-all active:scale-95"
        >
          仮眠を予約する
        </Link>
      </section>

      {/* Footer */}
      <footer className="px-6 py-6 text-center text-xs text-text-light border-t border-border">
        <p>&copy; 2026 NapGO. All rights reserved.</p>
      </footer>
    </main>
  );
}
