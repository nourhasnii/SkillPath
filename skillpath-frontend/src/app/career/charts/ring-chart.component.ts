import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type ChartTone = 'violet' | 'emerald' | 'amber' | 'rose';

/**
 * Circular progress ring used for the career-readiness / match score.
 * Rendered as inline SVG so no charting dependency is required and the
 * result stays crisp on every screen density.
 */
@Component({
  selector: 'sp-ring-chart',
  standalone: true,
  template: `
    <figure class="ring">
      <svg
        [attr.width]="geometry().size"
        [attr.height]="geometry().size"
        [attr.viewBox]="'0 0 ' + geometry().size + ' ' + geometry().size"
        role="img"
        [attr.aria-label]="accessibleLabel()">
        <title>{{ accessibleLabel() }}</title>
        <circle
          class="ring-track"
          [attr.cx]="geometry().center"
          [attr.cy]="geometry().center"
          [attr.r]="geometry().radius"
          [attr.stroke-width]="geometry().thickness" />
        <circle
          class="ring-value"
          [class]="'ring-value tone-' + tone()"
          [attr.cx]="geometry().center"
          [attr.cy]="geometry().center"
          [attr.r]="geometry().radius"
          [attr.stroke-width]="geometry().thickness"
          [attr.stroke-dasharray]="geometry().circumference"
          [attr.stroke-dashoffset]="geometry().offset"
          [attr.transform]="'rotate(-90 ' + geometry().center + ' ' + geometry().center + ')'" />
      </svg>
      <figcaption class="ring-caption">
        <strong>{{ geometry().value }}<span aria-hidden="true">%</span></strong>
        @if (caption()) { <span class="ring-caption-text">{{ caption() }}</span> }
      </figcaption>
    </figure>
  `,
  styles: [`
    :host { display: block; }

    .ring { position: relative; display: grid; place-items: center; margin: 0; }

    .ring-track { fill: none; stroke: var(--sp-line); }

    .ring-value {
      fill: none;
      stroke-linecap: round;
      transition: stroke-dashoffset .7s cubic-bezier(.22, .61, .36, 1);
    }

    .tone-violet { stroke: var(--sp-indigo-500); }
    .tone-emerald { stroke: var(--sp-emerald-500); }
    .tone-amber { stroke: var(--sp-amber-500); }
    .tone-rose { stroke: var(--sp-rose-500); }

    .ring-caption {
      position: absolute;
      display: grid;
      justify-items: center;
      gap: 2px;
      text-align: center;
    }

    .ring-caption strong {
      color: var(--sp-ink-900);
      font-size: 34px;
      font-weight: 750;
      letter-spacing: -1.4px;
      line-height: 1;
    }

    .ring-caption strong span { font-size: 18px; font-weight: 700; }

    .ring-caption-text {
      max-width: 108px;
      color: var(--sp-ink-500);
      font-size: 10.5px;
      font-weight: 650;
      letter-spacing: .5px;
      text-transform: uppercase;
    }

    @media (prefers-reduced-motion: reduce) {
      .ring-value { transition: none; }
    }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class RingChartComponent {
  readonly value = input.required<number>();
  readonly size = input(180);
  readonly thickness = input(14);
  readonly tone = input<ChartTone>('violet');
  readonly caption = input('');
  readonly accessibleLabel = input('');

  protected readonly geometry = computed(() => {
    const size = this.size();
    const thickness = this.thickness();
    const radius = (size - thickness) / 2;
    const circumference = 2 * Math.PI * radius;
    const value = Math.min(100, Math.max(0, Math.round(this.value())));
    return {
      size,
      thickness,
      radius,
      circumference,
      center: size / 2,
      value,
      offset: circumference * (1 - value / 100)
    };
  });
}
