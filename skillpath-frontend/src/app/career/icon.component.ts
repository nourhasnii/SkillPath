import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

/**
 * Single icon set for the career workspace.
 *
 * Inline stroked SVG paths only — no icon font, no emoji, no added dependency,
 * so every glyph inherits the surrounding colour and stays crisp when scaled.
 */
const ICONS: Record<string, string[]> = {
  grid: ['M4 4h7v7H4z', 'M13 4h7v7h-7z', 'M4 13h7v7H4z', 'M13 13h7v7h-7z'],
  target: [
    'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18',
    'M12 7.5a4.5 4.5 0 1 0 0 9 4.5 4.5 0 0 0 0-9',
    'M12 10.5a1.5 1.5 0 1 0 0 3 1.5 1.5 0 0 0 0-3'
  ],
  path: ['M4 7h10', 'M4 12h16', 'M4 17h7', 'M6.5 5v4', 'M18.5 10v4', 'M9.5 15v4'],
  graph: [
    'M6 7a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5',
    'M18 13a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5',
    'M7 21a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5',
    'M8.3 6.4 15.7 9.3',
    'M7.5 15.9 6.6 8.4'
  ],
  user: ['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8', 'M4.5 20.5a7.5 7.5 0 0 1 15 0'],
  bell: ['M6 9a6 6 0 1 1 12 0c0 5 1.5 6 1.5 6H4.5S6 14 6 9', 'M10 19.5a2 2 0 0 0 4 0'],
  search: ['M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16', 'M21 21l-4.4-4.4'],
  chevron: ['M6 9.5l6 6 6-6'],
  menu: ['M4 7h16', 'M4 12h16', 'M4 17h16'],
  close: ['M6 6l12 12', 'M18 6L6 18'],
  logout: ['M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3', 'M10 17l-5-5 5-5', 'M5 12h10'],
  refresh: [
    'M20 11a8 8 0 0 0-13.7-5.5L4 7.7',
    'M4 3.5v4.2h4.2',
    'M4 13a8 8 0 0 0 13.7 5.5L20 16.3',
    'M20 20.5v-4.2h-4.2'
  ],
  check: ['M5 13l4.5 4.5L19 7'],
  alert: ['M12 4.2 21 20H3z', 'M12 10v4.2', 'M12 17v.1'],
  arrowRight: ['M5 12h14', 'M13 6l6 6-6 6'],
  arrowLeft: ['M19 12H5', 'M11 18l-6-6 6-6'],
  clock: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18', 'M12 7.2v5.2l3.4 2'],
  layers: ['M12 3 3 8l9 5 9-5-9-5', 'M3 13l9 5 9-5', 'M3 17.5l9 5 9-5'],
  sparkle: ['M12 3l1.9 5.4L19.5 10l-5.6 1.6L12 17l-1.9-5.4L4.5 10l5.6-1.6z'],
  external: ['M14 4h6v6', 'M20 4l-9 9', 'M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5'],
  zoomIn: ['M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16', 'M21 21l-4.4-4.4', 'M11 8.5v5', 'M8.5 11h5'],
  zoomOut: ['M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16', 'M21 21l-4.4-4.4', 'M8.5 11h5'],
  fit: ['M4 9.5V4h5.5', 'M20 9.5V4h-5.5', 'M4 14.5V20h5.5', 'M20 14.5V20h-5.5'],
  filter: ['M4 5h16l-6 7.2V20l-4-2.2v-5.6z'],
  book: ['M4 5.6A2.6 2.6 0 0 1 6.6 3H20v15.4H6.6A2.6 2.6 0 0 0 4 21z', 'M4 5.6V21'],
  flag: ['M6 21V4', 'M6 4h11l-2 4 2 4H6'],
  list: ['M8 6h12', 'M8 12h12', 'M8 18h12', 'M4.2 6h.01', 'M4.2 12h.01', 'M4.2 18h.01'],
  branch: ['M6 20V9', 'M6 4.5v.01', 'M18 20v-6.5a3 3 0 0 0-3-3H6', 'M18 8v.01'],
  briefcase: [
    'M5.5 7.5h13A1.5 1.5 0 0 1 20 9v9.5a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5V9a1.5 1.5 0 0 1 1.5-1.5z',
    'M9 7.5V6.2A1.7 1.7 0 0 1 10.7 4.5h2.6A1.7 1.7 0 0 1 15 6.2v1.3',
    'M4 12.5h16'
  ],
  trend: ['M4 16.5l5.5-5.5 3.5 3.5L20 7.5', 'M20 7.5h-4.6', 'M20 7.5v4.6'],
  graduation: [
    'M12 4.5 2.5 9 12 13.5 21.5 9 12 4.5',
    'M6.5 11.2V16c0 1.5 2.5 2.8 5.5 2.8s5.5-1.3 5.5-2.8v-4.8',
    'M21.5 9v5.5'
  ],
  compass: [
    'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18',
    'M15.4 8.6 13.2 13.2 8.6 15.4l2.2-4.6z'
  ]
};

@Component({
  selector: 'sp-icon',
  standalone: true,
  template: `
    <svg
      [attr.width]="size()"
      [attr.height]="size()"
      [attr.viewBox]="'0 0 24 24'"
      fill="none"
      [attr.stroke]="'currentColor'"
      stroke-width="1.7"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false">
      @for (path of paths(); track $index) {
        <path [attr.d]="path" />
      }
    </svg>
  `,
  styles: [`
    :host { display: inline-flex; flex: 0 0 auto; }
    svg { display: block; }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class IconComponent {
  readonly name = input.required<string>();
  readonly size = input(18);

  protected readonly paths = computed(() => ICONS[this.name()] ?? ICONS['grid']);
}
