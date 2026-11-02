import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { courseFormat } from './career.service';

const PALETTES: { from: string; to: string; ink: string }[] = [
  { from: '#4338CA', to: '#7C6BF0', ink: '#DCD8FF' },
  { from: '#0B1120', to: '#31386B', ink: '#B9C4E8' },
  { from: '#06B6D4', to: '#4338CA', ink: '#D3F4FB' },
  { from: '#6D5AE6', to: '#22D3EE', ink: '#E4E2FF' },
  { from: '#1E2A47', to: '#6D5AE6', ink: '#C7CBF0' },
  { from: '#0F766E', to: '#22D3EE', ink: '#CFF3EC' }
];

/**
 * Deterministic course illustration.
 *
 * The ontology ships no thumbnails, so instead of arbitrary stock images this
 * renders a stable abstract cover derived from the course identifier and its
 * delivery class — always relevant, never a broken link.
 */
@Component({
  selector: 'sp-course-cover',
  standalone: true,
  template: `
    <svg viewBox="0 0 320 180" preserveAspectRatio="xMidYMid slice" role="img" [attr.aria-label]="description()">
      <title>{{ description() }}</title>
      <defs>
        <linearGradient [attr.id]="gradientId()" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" [attr.stop-color]="palette().from" />
          <stop offset="100%" [attr.stop-color]="palette().to" />
        </linearGradient>
      </defs>
      <rect width="320" height="180" [attr.fill]="'url(#' + gradientId() + ')'" />

      @switch (motif()) {
        @case (0) {
          <g [attr.stroke]="palette().ink" fill="none" stroke-width="1.4" opacity=".65">
            <circle cx="232" cy="66" r="26" />
            <circle cx="232" cy="66" r="46" />
            <circle cx="232" cy="66" r="68" />
          </g>
          <circle cx="232" cy="66" r="7" [attr.fill]="palette().ink" opacity=".9" />
          <path d="M18 150 L74 96 L122 128 L176 62" [attr.stroke]="palette().ink" fill="none" stroke-width="2.4" stroke-linecap="round" opacity=".55" />
        }
        @case (1) {
          <g [attr.fill]="palette().ink" opacity=".38">
            <rect x="26" y="104" width="18" height="46" rx="6" />
            <rect x="54" y="86" width="18" height="64" rx="6" />
            <rect x="82" y="66" width="18" height="84" rx="6" />
            <rect x="110" y="46" width="18" height="104" rx="6" />
          </g>
          <path d="M26 92 L63 74 L91 54 L119 34" [attr.stroke]="palette().ink" fill="none" stroke-width="2.4" stroke-linecap="round" opacity=".75" />
          <circle cx="248" cy="118" r="42" [attr.fill]="palette().ink" opacity=".14" />
        }
        @default {
          <g [attr.stroke]="palette().ink" stroke-width="1.6" opacity=".62">
            <line x1="206" y1="52" x2="256" y2="34" />
            <line x1="206" y1="52" x2="240" y2="92" />
            <line x1="206" y1="52" x2="168" y2="96" />
            <line x1="240" y1="92" x2="168" y2="96" />
          </g>
          <g [attr.fill]="palette().ink">
            <circle cx="206" cy="52" r="9" />
            <circle cx="256" cy="34" r="6" opacity=".8" />
            <circle cx="240" cy="92" r="6" opacity=".8" />
            <circle cx="168" cy="96" r="6" opacity=".8" />
          </g>
          <rect x="22" y="120" width="120" height="8" rx="4" [attr.fill]="palette().ink" opacity=".3" />
          <rect x="22" y="136" width="78" height="8" rx="4" [attr.fill]="palette().ink" opacity=".2" />
        }
      }
    </svg>
  `,
  styles: [`
    :host { display: block; }
    svg { display: block; width: 100%; height: 100%; }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class CourseCoverComponent {
  readonly courseId = input.required<string>();
  readonly courseType = input<string | null>(null);

  protected readonly palette = computed(() => PALETTES[hash(this.courseId()) % PALETTES.length]);
  protected readonly motif = computed(() => hash(`${this.courseId()}#motif`) % 3);
  protected readonly gradientId = computed(() => `sp-cover-${this.courseId().replace(/[^A-Za-z0-9]/g, '')}`);
  protected readonly description = computed(
    () => `${courseFormat(this.courseType())} illustration`
  );
}

function hash(value: string): number {
  let result = 0;
  for (let index = 0; index < value.length; index += 1) {
    result = (result * 31 + value.charCodeAt(index)) % 100000;
  }
  return result;
}
