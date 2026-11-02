import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export interface RadarAxis {
  label: string;
  /** `true` when the ontology declares this required skill as acquired. */
  mastered: boolean;
}

interface RadarGeometry {
  size: number;
  center: number;
  radius: number;
  rings: string[];
  spokes: { x1: number; y1: number; x2: number; y2: number }[];
  requiredPoints: string;
  masteredPoints: string;
  vertices: { x: number; y: number }[];
  labels: { x: number; y: number; anchor: string; text: string; mastered: boolean }[];
}

/**
 * "Mastery footprint" radar: one axis per required skill of the target occupation.
 *
 * The ontology records skill acquisition as a declared assertion, not a graded
 * level, so each axis is binary — the outer polygon is the full requirement and
 * the inner polygon only reaches the axes the profile has declared as mastered.
 * No proficiency value is invented.
 */
@Component({
  selector: 'sp-radar-chart',
  standalone: true,
  template: `
    <figure class="radar">
      <svg
        [attr.viewBox]="'0 0 ' + geometry().size + ' ' + geometry().size"
        role="img"
        [attr.aria-label]="accessibleLabel()">
        <title>{{ accessibleLabel() }}</title>

        @for (ring of geometry().rings; track $index) {
          <polygon class="radar-ring" [attr.points]="ring" />
        }
        @for (spoke of geometry().spokes; track $index) {
          <line class="radar-spoke" [attr.x1]="spoke.x1" [attr.y1]="spoke.y1" [attr.x2]="spoke.x2" [attr.y2]="spoke.y2" />
        }

        <polygon class="radar-required" [attr.points]="geometry().requiredPoints" />
        <polygon class="radar-mastered" [attr.points]="geometry().masteredPoints" />

        @for (vertex of geometry().vertices; track $index) {
          <circle class="radar-vertex" [attr.cx]="vertex.x" [attr.cy]="vertex.y" r="3.6" />
        }

        @for (label of geometry().labels; track $index) {
          <text
            class="radar-label"
            [class.is-mastered]="label.mastered"
            [attr.x]="label.x"
            [attr.y]="label.y"
            [attr.text-anchor]="label.anchor"
            dominant-baseline="middle">{{ label.text }}</text>
        }
      </svg>

      <figcaption class="radar-legend">
        <span class="legend-item"><i class="swatch required" aria-hidden="true"></i> Required by the occupation</span>
        <span class="legend-item"><i class="swatch mastered" aria-hidden="true"></i> Mastered by you</span>
      </figcaption>
    </figure>
  `,
  styles: [`
    :host { display: block; }
    .radar { display: grid; gap: 12px; margin: 0; }
    svg { width: 100%; height: auto; overflow: visible; }

    .radar-ring { fill: none; stroke: var(--sp-line); stroke-width: 1; }
    .radar-spoke { stroke: var(--sp-line); stroke-width: 1; }

    .radar-required {
      fill: rgba(109, 90, 230, .09);
      stroke: var(--sp-violet-400);
      stroke-width: 1.4;
      stroke-dasharray: 5 4;
    }

    .radar-mastered {
      fill: rgba(91, 79, 233, .32);
      stroke: var(--sp-indigo-500);
      stroke-width: 2;
      stroke-linejoin: round;
    }

    .radar-vertex { fill: var(--sp-indigo-500); }

    .radar-label {
      fill: var(--sp-ink-500);
      font-family: var(--sp-font);
      font-size: 11px;
      font-weight: 600;
    }

    .radar-label.is-mastered { fill: var(--sp-indigo-600); font-weight: 750; }

    .radar-legend { display: flex; flex-wrap: wrap; gap: 8px 18px; }
    .legend-item { display: inline-flex; align-items: center; gap: 7px; color: var(--sp-ink-500); font-size: 11.5px; font-weight: 600; }
    .swatch { width: 11px; height: 11px; border-radius: 3px; }
    .swatch.required { border: 1.4px dashed var(--sp-violet-400); background: rgba(109, 90, 230, .12); }
    .swatch.mastered { background: var(--sp-indigo-500); }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class RadarChartComponent {
  readonly axes = input.required<RadarAxis[]>();
  readonly size = input(340);
  readonly accessibleLabel = input('');

  protected readonly geometry = computed<RadarGeometry>(() => {
    const axes = this.axes();
    const size = this.size();
    const center = size / 2;
    const radius = center - 58;
    const count = Math.max(axes.length, 1);
    const step = (Math.PI * 2) / count;
    const start = -Math.PI / 2;

    const pointAt = (factor: number, index: number) => {
      const angle = start + step * index;
      return {
        x: center + Math.cos(angle) * radius * factor,
        y: center + Math.sin(angle) * radius * factor
      };
    };

    const rings = [0.25, 0.5, 0.75, 1].map(factor =>
      axes
        .map((_, index) => {
          const point = pointAt(factor, index);
          return `${point.x.toFixed(1)},${point.y.toFixed(1)}`;
        })
        .join(' ')
    );

    const spokes = axes.map((_, index) => {
      const outer = pointAt(1, index);
      return { x1: center, y1: center, x2: outer.x, y2: outer.y };
    });

    const requiredPoints = axes
      .map((_, index) => {
        const point = pointAt(1, index);
        return `${point.x.toFixed(1)},${point.y.toFixed(1)}`;
      })
      .join(' ');

    const masteredPoints = axes
      .map((axis, index) => {
        const point = pointAt(axis.mastered ? 1 : 0.045, index);
        return `${point.x.toFixed(1)},${point.y.toFixed(1)}`;
      })
      .join(' ');

    const vertices = axes
      .map((axis, index) => (axis.mastered ? pointAt(1, index) : null))
      .filter((point): point is { x: number; y: number } => point !== null);

    const labels = axes.map((axis, index) => {
      const angle = start + step * index;
      const point = pointAt(1.13, index);
      const cos = Math.cos(angle);
      const anchor = Math.abs(cos) < 0.25 ? 'middle' : cos > 0 ? 'start' : 'end';
      return {
        x: point.x,
        y: point.y,
        anchor,
        text: truncate(axis.label, 16),
        mastered: axis.mastered
      };
    });

    return {
      size,
      center,
      radius,
      rings,
      spokes,
      requiredPoints,
      masteredPoints,
      vertices,
      labels
    };
  });
}

function truncate(value: string, max: number): string {
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}
