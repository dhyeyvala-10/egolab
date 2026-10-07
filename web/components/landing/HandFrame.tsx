/** Joints of one tracked hand: the wrist, then four joints per finger, thumb to little finger. */
const WRIST: [number, number] = [250, 340];
const FINGERS: [number, number][][] = [
  [[205, 305], [175, 272], [155, 247], [140, 226]],
  [[225, 240], [222, 195], [220, 164], [218, 138]],
  [[256, 234], [258, 184], [260, 152], [262, 124]],
  [[284, 242], [292, 196], [298, 166], [302, 142]],
  [[306, 260], [322, 224], [332, 202], [340, 182]],
];

const points = (pts: [number, number][]) => pts.map(([x, y]) => `${x},${y}`).join(" ");

/**
 * Hero illustration: a video frame with a hand skeleton reaching for a cup, and the movement events
 * detected along the way. Drawn, not real data; the frame stays dark in both themes like a video.
 */
export function HandFrame() {
  return (
    <div className="relative mx-auto w-full max-w-[600px] pb-16">
      <div className="overflow-hidden rounded-[28px] border border-line shadow-[0_30px_60px_-30px_rgba(40,25,10,0.45)]">
        <svg viewBox="0 0 600 420" className="block h-auto w-full" role="img" aria-label="A video frame with a tracked hand reaching for a cup">
          <rect width="600" height="420" fill="#231d17" />
          <path d="M0 330 L600 300 L600 420 L0 420 Z" fill="#2d251d" />
          <g stroke="#e38b5b" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round">
            {FINGERS.map((finger, i) => (
              <polyline key={i} points={points([WRIST, ...finger])} />
            ))}
            <polyline points={points(FINGERS.map((f) => f[0]))} />
          </g>
          <g fill="#efe5d3">
            <circle cx={WRIST[0]} cy={WRIST[1]} r="6" />
            {FINGERS.flat().map(([x, y]) => (
              <circle key={`${x}-${y}`} cx={x} cy={y} r="4.5" />
            ))}
          </g>
          <rect x="390" y="170" width="140" height="160" rx="6" fill="none" stroke="#8fb8a2" strokeWidth="2.5" strokeDasharray="8 6" />
          <path d="M420 215 h70 v90 a10 10 0 0 1 -10 10 h-50 a10 10 0 0 1 -10 -10 Z" fill="#4a3f33" />
          <path d="M490 235 a22 22 0 0 1 0 44" fill="none" stroke="#4a3f33" strokeWidth="10" />
          <rect x="390" y="140" width="52" height="24" rx="6" fill="#8fb8a2" />
          <text x="401" y="157" fontFamily="ui-monospace, monospace" fontSize="13" fill="#16130f">cup</text>
          <rect x="102" y="98" width="196" height="24" rx="6" fill="#e38b5b" />
          <text x="112" y="115" fontFamily="ui-monospace, monospace" fontSize="13" fill="#16130f">right hand · 21 joints</text>
        </svg>
      </div>
      <div className="absolute bottom-0 right-0 flex w-[min(360px,90%)] flex-col gap-2.5 rounded-3xl border border-line bg-canvas p-4 shadow-sm">
        <div className="font-mono text-xs text-ink-3">Movement events, frame by frame</div>
        <div className="flex h-8 gap-1 text-xs font-bold" aria-hidden>
          <div className="flex flex-[3] items-center rounded-lg bg-hover px-2.5 text-ink-3">idle</div>
          <div className="flex flex-[4] items-center rounded-lg bg-accent-soft px-2.5 text-accent">reach</div>
          <div className="flex flex-[5] items-center rounded-lg bg-accent px-2.5 text-on-accent">grasp</div>
          <div className="flex flex-[3] items-center rounded-lg bg-sage-soft px-2.5 text-sage">lift</div>
        </div>
        <p className="sr-only">An idle hand reaches for the cup, grasps it, and lifts it.</p>
      </div>
    </div>
  );
}
