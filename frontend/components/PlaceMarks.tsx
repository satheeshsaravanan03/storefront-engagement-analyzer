import type { Point } from '@/lib/api';

/* A shop as it is drawn: the editor passes unfinished shops, the results page finished ones. */
export interface ShopMark {
  name: string;
  door: Point[];          // 0 to 2 points
  inside: Point | null;   // the pin
  front: Point[];
}

// One colour per shop, in the order the shops were marked
export const SHOP_COLORS = ['#00C800', '#008CFF', '#C800C8', '#FFB400', '#5050FF', '#00C878', '#FF7800', '#00B4B4'];

/* The shop area the engine uses (backend/places.py to_pixels): the door line pushed toward the pin by as far
   as the pin is from the middle of the door. Null until there is a door line and a pin. */
export function shopArea(d: ShopMark): Point[] | null {
  if (d.door.length < 2 || !d.inside) return null;
  const [a, b] = d.door;
  const vx = d.inside[0] - (a[0] + b[0]) / 2;
  const vy = d.inside[1] - (a[1] + b[1]) / 2;
  return [a, b, [b[0] + vx, b[1] + vy], [a[0] + vx, a[1] + vy]];
}

function Pill({ text, x, y, color, u, faint }: { text: string; x: number; y: number; color: string; u: number; faint?: boolean }) {
  const fs = 11 * u;
  const w = text.length * fs * 0.58 + 10 * u;
  const h = fs + 6 * u;
  return (
    <g transform={`translate(${x - w / 2} ${y - h / 2})`} opacity={faint ? 0.55 : 0.92}>
      <rect width={w} height={h} rx={h / 2} fill={color} />
      <text x={w / 2} y={h / 2} fontSize={fs} fontWeight={600} fill="#fff" textAnchor="middle" dominantBaseline="central"
        fontFamily="ui-sans-serif, system-ui, sans-serif">{text}</text>
    </g>
  );
}

/* The marks as SVG, in the frame's own pixel space. `unit` is frame pixels per screen pixel, so lines and
   labels keep the same size on screen at any zoom. Thin and light, so the video underneath stays visible. */
export function PlaceMarks({ marks, width, height, unit, active, labels = true }: {
  marks: ShopMark[];
  width: number;
  height: number;
  unit: number;
  active?: number;
  labels?: boolean;
}) {
  const P = (p: Point): [number, number] => [p[0] * width, p[1] * height];
  const poly = (pts: Point[]) => pts.map(p => P(p).join(',')).join(' ');
  const u = unit;

  return (
    <g pointerEvents="none">
      {marks.map((d, i) => {
        const color = SHOP_COLORS[i % SHOP_COLORS.length];
        const strong = i === active ? 1.35 : 1;
        const area = shopArea(d);
        const [a, b] = d.door.length === 2 ? [P(d.door[0]), P(d.door[1])] : [null, null];
        const mid = a && b ? [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] : null;
        const pin = d.inside ? P(d.inside) : null;
        // the pin's offset from the door, which also marks where the outside is (the same distance the other way)
        const v = mid && pin ? [pin[0] - mid[0], pin[1] - mid[1]] : null;
        const len = v ? Math.hypot(v[0], v[1]) || 1 : 1;

        return (
          <g key={i}>
            {d.front.length >= 3 && (
              <polygon points={poly(d.front)} fill={color} fillOpacity={0.14} stroke={color} strokeOpacity={0.9}
                strokeWidth={1.5 * u} strokeDasharray={`${5 * u} ${4 * u}`} />
            )}
            {area && a && b && v && (
              <>
                <polygon points={[a, b, [b[0] - v[0], b[1] - v[1]], [a[0] - v[0], a[1] - v[1]]].map(p => p.join(',')).join(' ')}
                  fill={color} fillOpacity={0.04} stroke={color} strokeOpacity={0.35} strokeWidth={1 * u} strokeDasharray={`${3 * u} ${4 * u}`} />
                <polygon points={poly(area)} fill={color} fillOpacity={0.16 * strong} />
              </>
            )}
            {a && b && (
              <>
                <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="#fff" strokeOpacity={0.85} strokeWidth={4.5 * u} strokeLinecap="round" />
                <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={color} strokeWidth={2 * u * strong} strokeLinecap="round" />
              </>
            )}
            {mid && pin && (
              <>
                <line x1={mid[0]} y1={mid[1]} x2={pin[0]} y2={pin[1]} stroke={color} strokeWidth={1.4 * u} strokeDasharray={`${4 * u} ${4 * u}`} />
                <circle cx={pin[0]} cy={pin[1]} r={6 * u} fill="#fff" />
                <circle cx={pin[0]} cy={pin[1]} r={4 * u} fill={color} />
              </>
            )}
            {labels && mid && v && (
              <>
                <Pill text={d.name || 'Shop'} x={mid[0] - (v[0] / len) * 22 * u} y={mid[1] - (v[1] / len) * 22 * u} color={color} u={u} />
                <Pill text="IN" x={pin![0] + (v[0] / len) * 16 * u} y={pin![1] + (v[1] / len) * 16 * u} color={color} u={u} />
                <Pill text="OUT" x={mid[0] - v[0]} y={mid[1] - v[1]} color={color} u={u} faint />
              </>
            )}
            {labels && !mid && d.door.length === 1 && (
              <Pill text={d.name || 'Shop'} x={P(d.door[0])[0]} y={P(d.door[0])[1] - 16 * u} color={color} u={u} />
            )}
          </g>
        );
      })}
    </g>
  );
}
