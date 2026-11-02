import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { SkillStatus, SKILL_STATUS_META } from '../career.service';

export interface SkillBar {
  id: string;
  label: string;
  status: SkillStatus;
  /** Extra context rendered under the bar (priority, recommended training…). */
  note: string;
}

/**
 * Horizontal target-vs-actual chart.
 *
 * The thin upper line is the level the occupation requires. The thick lower
 * line is the coverage declared in the ontology: solid for a mastered skill,
 * hatched for a skill covered by a training that is still in progress, empty
 * for a skill that is genuinely missing.
 */
@Component({
  selector: 'sp-skill-bar-chart',
  standalone: true,
  template: `
    <ul class="bars" role="list">
      @for (bar of bars(); track bar.id) {
        <li class="bar-row">
          <div class="bar-head">
            <span class="bar-label">{{ bar.label }}</span>
            <span class="sp-badge" [class]="'sp-badge ' + badgeClass(bar.status)">
              {{ statusLabel(bar.status) }}
            </span>
          </div>

          <div class="bar-tracks" role="img" [attr.aria-label]="describe(bar)">
            <span class="track track-required" aria-hidden="true"></span>
            <span class="track track-coverage" aria-hidden="true">
              <span class="coverage-fill" [class]="'coverage-fill ' + bar.status"></span>
            </span>
          </div>

          <p class="bar-note">{{ bar.note }}</p>
        </li>
      }
    </ul>

    <div class="bars-legend">
      <span class="legend-item"><i class="swatch swatch-required" aria-hidden="true"></i> Required level</span>
      <span class="legend-item"><i class="swatch swatch-mastered" aria-hidden="true"></i> Mastered</span>
      <span class="legend-item"><i class="swatch swatch-progress" aria-hidden="true"></i> In progress</span>
      <span class="legend-item"><i class="swatch swatch-missing" aria-hidden="true"></i> Not covered yet</span>
    </div>
  `,
  styles: [`
    :host { display: block; }
    .bars { display: grid; gap: 16px; margin: 0; padding: 0; list-style: none; }

    .bar-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
    .bar-label { overflow: hidden; color: var(--sp-ink-900); font-size: 13px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }

    .bar-tracks { display: grid; gap: 5px; margin: 8px 0 6px; }

    .track { display: block; border-radius: 999px; }
    .track-required { height: 4px; background: linear-gradient(90deg, var(--sp-violet-100), #DAD5FA); }
    .track-coverage { height: 10px; background: var(--sp-surface-muted); box-shadow: inset 0 0 0 1px var(--sp-line); overflow: hidden; }

    .coverage-fill { display: block; height: 100%; border-radius: 999px; width: 0; }
    .coverage-fill.acquise { width: 100%; background: var(--sp-gradient-brand); }
    .coverage-fill.en_cours {
      width: 100%;
      background: repeating-linear-gradient(115deg, var(--sp-amber-500) 0 6px, #FBC96B 6px 12px);
    }
    .coverage-fill.manquante { width: 0; }

    .bar-note { margin: 0; color: var(--sp-ink-500); font-size: 11.5px; line-height: 1.55; }

    .bars-legend { display: flex; flex-wrap: wrap; gap: 8px 18px; margin-top: 20px; }
    .legend-item { display: inline-flex; align-items: center; gap: 7px; color: var(--sp-ink-500); font-size: 11.5px; font-weight: 600; }
    .swatch { width: 16px; height: 8px; border-radius: 999px; }
    .swatch-required { background: linear-gradient(90deg, var(--sp-violet-100), #DAD5FA); }
    .swatch-mastered { background: var(--sp-gradient-brand); }
    .swatch-progress { background: repeating-linear-gradient(115deg, var(--sp-amber-500) 0 4px, #FBC96B 4px 8px); }
    .swatch-missing { background: var(--sp-surface-muted); box-shadow: inset 0 0 0 1px var(--sp-line-strong); }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class SkillBarChartComponent {
  readonly bars = input.required<SkillBar[]>();

  protected statusLabel(status: SkillStatus): string {
    return SKILL_STATUS_META[status].label;
  }

  protected badgeClass(status: SkillStatus): string {
    return `sp-badge-${SKILL_STATUS_META[status].tone}`;
  }

  protected describe(bar: SkillBar): string {
    return `${bar.label}: ${SKILL_STATUS_META[bar.status].label}. ${SKILL_STATUS_META[bar.status].description}`;
  }
}
