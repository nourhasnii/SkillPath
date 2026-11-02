import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { LevelInfo } from '../auth/auth.service';
import { IconComponent } from './icon.component';
import { levelLabel, levelTone } from './career.service';

/**
 * "Required level vs Your level" comparison.
 *
 * Both sides come straight from the ontology (`sp:necessiteNiveau` of the
 * occupation and `sp:aPourNiveau` of the profile). The block renders nothing
 * when the occupation declares no required level.
 */
@Component({
  selector: 'sp-level-compare',
  standalone: true,
  imports: [IconComponent],
  template: `
    @if (requiredLevel(); as required) {
      <div class="level-compare">
        <div class="level-chip">
          <span class="level-chip-label">Required level</span>
          <span [class]="badgeClass(required)">{{ label(required) }}</span>
        </div>
        <sp-icon name="arrowRight" [size]="18" />
        <div class="level-chip">
          <span class="level-chip-label">Your level</span>
          @if (level(); as mine) {
            <span [class]="badgeClass(mine)">{{ label(mine) }}</span>
          } @else {
            <span class="sp-badge sp-badge-neutral">Not evaluated</span>
          }
        </div>
      </div>
    }
  `,
  styles: [`
    :host { display: block; }

    .level-compare {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 14px;
      padding: 16px 18px;
      border: 1px solid var(--sp-line);
      border-radius: var(--sp-radius-md);
      background: var(--sp-surface-muted);
    }

    .level-chip { display: grid; gap: 6px; }

    .level-chip-label {
      color: var(--sp-ink-400);
      font-size: 10.5px;
      font-weight: 750;
      letter-spacing: .7px;
      text-transform: uppercase;
    }

    sp-icon { color: var(--sp-ink-400); }
  `],
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class LevelCompareComponent {
  /** Overall readiness level of the profile (`sp:aPourNiveau`). */
  readonly level = input<LevelInfo | null>(null);
  /** Level required by the target occupation (`sp:necessiteNiveau`). */
  readonly requiredLevel = input<LevelInfo | null>(null);

  protected label(value: LevelInfo): string {
    return levelLabel(value);
  }

  protected badgeClass(value: LevelInfo): string {
    return `sp-badge sp-badge-${levelTone(value)}`;
  }
}
