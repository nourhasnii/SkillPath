import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export interface DistributionSegment {
  key: string;
  label: string;
  value: number;
  /** CSS custom property for the swatch color. */
  color: string;
}

interface DistributionArc extends DistributionSegment {
  dasharray: string;
  offset: number;
  share: number;
}

/**
 * Donut distribution chart (mastered / in progress / missing).
 * Pure SVG, so it prints, scales and stays accessible without a chart library.
 */
@Component({
  selector: 'sp-distribution-chart',
  standalone: true,
  template: `
    <div class="distribution">
      <figure class="donut">
        <svg
          [attr.width]="size()"
          [attr.height]="size()"
          [attr.viewBox]="'0 0 ' + size() + ' ' + size()"
          role="img"
          [attr.aria-label]="accessibleLabel()">
          <title>{{ accessibleLabel() }}</title>
          <circle
            class="donut-track"
            [attr.cx]="center()"
            [attr.cy]="center()"
            [attr.r]="radius()"
            [attr.stroke-width]="thickness()" />
          @for (arc of arcs(); track arc.key) {
            <circle
              class="donut-arc"
              [attr.cx]="center()"
              [attr.cy]="center()"
              [attr.r]="radius()"
              [attr.stroke-width]="thickness()"
              [attr.stroke]="arc.color"
              [attr.stroke-dasharray]="arc.dasharray"
              [attr.stroke-dashoffset]="arc.offset"
              [attr.transform]="'rotate(-90 ' + center() + ' ' + center() + ')'" />
          }
        </svg>
        <figcaption class="donut-total">
          <strong>{{ total() }}</strong>
          <span>{{ unit() }}</span>
        </figcaption>
      </figure>

      <ul class="distribution-legend" role="list">
        @for (arc of arcs(); track arc.key) {
          <li>
            <i class="swatch" [style.background]="arc.color" aria-hidden="true"></i>
            <span class="legend-label">{{ arc.label }}</span>
            <span class="legend-value">
              <strong>{{ arc.value }}</strong>
              <small>{{ arc.share }}%</small>
            </span>
          </li>
        }
      </ul>
    </div>
  `,
  styles: [`
    :host { display: block; }
    .distribution { display: flex; flex-wrap: wrap; align-items: center; gap: 26px; }

    .donut { position: relative; display: grid; place-items: center; margin: 0; }
    .donut-track { fill: none; stroke: var(--sp-line); }
    .donut-arc { fill: none; stroke-linecap: butt; transition: stroke-dasharray .6s ease; }

    .donut-total {
      position: absolute;
      display: grid;
      justify-items: center;
      line-height: 1;
    }
    .donut-total strong { color: var(--sp-ink-900); font-size: 30px; font-weight: 750; letter-spacing: -1.2px; }
    .donut-total span { margin-top: 3px; color: var(--sp-ink-500); font-size: 10.5px; font-weight: 650; letter-spacing: .9px; text-transform: uppercase; }

    .distribution-legend { display: grid; flex: 1 1 190px; gap: 12px; margin: 0; padding: 0; list-style: none; }
    .distribution-legend li { display: flex; align-items: center; gap: 10px; }
    .swatch { width: 11px; height: 11px; flex: 0 0 11px; border-radius: 4px; }
    .legend-label { color: var(--sp-ink-700); font-size: 12.5px; font-weight: 600; }
    .legend-value { display: inline-flex; align-items: baseline; gap: 6px; margin-left: auto; }
    .legend-value strong { color: var(--sp-ink-900); font-size: 14px; font-weight: 750; }
    .legend-value small { color: var(--sp-ink-400); font-size: 11px; font-weight: 650; }

    @media (prefers-reduced-motion: reduce) {
      .donut-arc { transition: none; }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DistributionChartComponent {
  readonly segments = input.required<DistributionSegment[]>();
  readonly size = input(180);
  readonly thickness = input(16);
  readonly accessibleLabel = input('');
  /** Caption shown under the centre total (e.g. "skills", "profiles"). */
  readonly unit = input('skills');

  protected readonly total = computed(() =>
    this.segments().reduce((sum, segment) => sum + segment.value, 0)
  );

  protected readonly center = computed(() => this.size() / 2);
  protected readonly radius = computed(() => (this.size() - this.thickness()) / 2);

  protected readonly arcs = computed<DistributionArc[]>(() => {
    const circumference = 2 * Math.PI * this.radius();
    const total = this.total();
    let cumulative = 0;
    return this.segments().map(segment => {
      const share = total ? segment.value / total : 0;
      const gap = share > 0 && share < 1 && segment.value > 0 ? 2 : 0;
      const length = Math.max(share * circumference - gap, 0);
      const arc: DistributionArc = {
        ...segment,
        share: Math.round(share * 100),
        dasharray: `${length.toFixed(2)} ${(circumference - length).toFixed(2)}`,
        offset: -(cumulative * circumference)
      };
      cumulative += share;
      return arc;
    });
  });
}
