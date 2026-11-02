import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';
import { finalize } from 'rxjs';

import { apiErrorMessage } from '../../dashboard/dashboard-data.service';
import { LevelInfo } from '../../auth/auth.service';
import { LevelCompareComponent } from '../../career/level-compare.component';
import {
  ChartTone,
  RingChartComponent
} from '../../career/charts/ring-chart.component';
import { RadarAxis, RadarChartComponent } from '../../career/charts/radar-chart.component';
import { SkillBar, SkillBarChartComponent } from '../../career/charts/skill-bar-chart.component';
import {
  DistributionChartComponent,
  DistributionSegment
} from '../../career/charts/distribution-chart.component';
import {
  CareerSelection,
  CareerSelectorComponent
} from '../../career/career-selector.component';
import { RecommendedForYouComponent } from '../../career/recommended-for-you.component';
import { IconComponent } from '../../career/icon.component';
import {
  CareerService,
  SkillComparison,
  SkillGapReport,
  SkillPriority,
  SkillStatus,
  SKILL_PRIORITY_META,
  SKILL_STATUS_META,
  humanizeIdentifier
} from '../../career/career.service';

type SkillTab = 'all' | SkillStatus;

interface TabItem {
  key: SkillTab;
  label: string;
  count: number;
}

interface ReadinessBand {
  label: string;
  tone: ChartTone;
  narrative: string;
}

const STATUS_ORDER: Record<SkillStatus, number> = { manquante: 0, en_cours: 1, acquise: 2 };
const PRIORITY_ORDER: Record<SkillPriority, number> = { haute: 0, moyenne: 1, basse: 2, aucune: 3 };

@Component({
  selector: 'app-skill-gap',
  standalone: true,
  imports: [
    RouterLink,
    CareerSelectorComponent,
    RingChartComponent,
    RadarChartComponent,
    SkillBarChartComponent,
    DistributionChartComponent,
    LevelCompareComponent,
    IconComponent,
    RecommendedForYouComponent
  ],
  templateUrl: './skill-gap.component.html',
  styleUrl: './skill-gap.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class SkillGapComponent implements OnInit {
  private readonly career = inject(CareerService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly selection = signal<CareerSelection | null>(null);
  protected readonly loading = signal(false);
  protected readonly error = signal('');
  protected readonly report = signal<SkillGapReport | null>(null);
  protected readonly activeTab = signal<SkillTab>('all');

  /** Overall readiness level of the signed-in profile (`sp:aPourNiveau`). */
  protected readonly level = computed(() => this.career.context()?.level ?? null);
  /** Level required by the occupation currently analysed (`sp:necessiteNiveau`). */
  protected readonly requiredLevel = signal<LevelInfo | null>(null);

  ngOnInit(): void {
    this.career.loadContext().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      error: () => undefined
    });
  }

  protected readonly occupationLabel = computed(() =>
    humanizeIdentifier(this.report()?.metier ?? '')
  );

  /**
   * Deterministic readiness banding over the real match score, paired with a
   * narrative built only from the returned counts — no fabricated scoring.
   */
  protected readonly readiness = computed<ReadinessBand | null>(() => {
    const report = this.report();
    if (!report) return null;

    const score = report.match_score;
    const band =
      score >= 85 ? { label: 'Ready', tone: 'emerald' as ChartTone }
      : score >= 60 ? { label: 'Nearly ready', tone: 'violet' as ChartTone }
      : score >= 35 ? { label: 'Developing', tone: 'amber' as ChartTone }
      : { label: 'Getting started', tone: 'rose' as ChartTone };

    const mastered = report.competences_acquises.length;
    const required = report.competences_requises.length;
    const inProgress = report.competences_en_cours.length;
    const missing = report.competences_manquantes.length;

    const narrative = required === 0
      ? `${humanizeIdentifier(report.metier)} has no required skill listed yet, so no gap can be measured.`
      : [
          `You have ${mastered} of the ${required} skills required for ${humanizeIdentifier(report.metier)}.`,
          missing > 0
            ? `${missing} still ${missing === 1 ? 'has' : 'have'} no matching training in your profile`
            : 'No skill is missing.',
          inProgress > 0
            ? `${inProgress} ${inProgress === 1 ? 'is' : 'are'} covered by a training in your profile but not yet counted as mastered.`
            : ''
        ]
          .filter(Boolean)
          .join(' ');

    return { ...band, narrative };
  });

  protected readonly tabs = computed<TabItem[]>(() => {
    const report = this.report();
    if (!report) return [];
    return [
      { key: 'all', label: 'All skills', count: report.competences.length },
      {
        key: 'acquise',
        label: 'Matched',
        count: report.competences.filter(skill => skill.statut === 'acquise').length
      },
      {
        key: 'en_cours',
        label: 'To improve',
        count: report.competences.filter(skill => skill.statut === 'en_cours').length
      },
      {
        key: 'manquante',
        label: 'Missing',
        count: report.competences.filter(skill => skill.statut === 'manquante').length
      }
    ];
  });

  protected readonly filteredSkills = computed<SkillComparison[]>(() => {
    const report = this.report();
    if (!report) return [];
    const tab = this.activeTab();
    const skills = tab === 'all'
      ? report.competences
      : report.competences.filter(skill => skill.statut === tab);
    return sortSkills(skills);
  });

  protected readonly radarAxes = computed<RadarAxis[]>(() =>
    (this.report()?.competences ?? []).map(skill => ({
      label: humanizeIdentifier(skill.label),
      mastered: skill.statut === 'acquise'
    }))
  );

  protected readonly radarLabel = computed(() => {
    const report = this.report();
    if (!report) return '';
    return `Mastery footprint for ${humanizeIdentifier(report.metier)}: ${report.competences_acquises.length} of ${report.competences_requises.length} required skills declared as mastered.`;
  });

  protected readonly distribution = computed<DistributionSegment[]>(() => {
    const report = this.report();
    if (!report) return [];
    return [
      { key: 'acquise', label: 'Mastered', value: countStatus(report, 'acquise'), color: '#5B4FE9' },
      { key: 'en_cours', label: 'In progress', value: countStatus(report, 'en_cours'), color: '#F59E0B' },
      { key: 'manquante', label: 'Missing', value: countStatus(report, 'manquante'), color: '#E11D48' }
    ];
  });

  protected readonly coverageBars = computed<SkillBar[]>(() =>
    sortSkills(this.report()?.competences ?? [])
      .slice(0, 8)
      .map(skill => ({
        id: skill.id,
        label: humanizeIdentifier(skill.label),
        status: skill.statut,
        note: coverageNote(skill)
      }))
  );

  protected readonly coverageNote = computed(() => {
    const total = this.report()?.competences.length ?? 0;
    const shown = this.coverageBars().length;
    return shown < total
      ? `Showing the ${shown} most urgent skills out of ${total}. The full breakdown is listed below.`
      : `All ${total} required skills are shown.`;
  });

  protected selectTab(tab: SkillTab): void {
    this.activeTab.set(tab);
  }

  protected onPreselected(selection: CareerSelection): void {
    this.load(selection);
  }

  protected onSubmitted(selection: CareerSelection): void {
    this.load(selection);
  }

  protected regenerate(): void {
    const selection = this.selection();
    if (selection) this.load(selection);
  }

  /** Maps a chart tone onto the badge palette used across the design system. */
  protected badgeTone(tone: ChartTone): string {
    const map: Record<ChartTone, string> = {
      emerald: 'sp-badge-success',
      amber: 'sp-badge-warning',
      rose: 'sp-badge-danger',
      violet: 'sp-badge-violet'
    };
    return map[tone];
  }

  protected statusLabel(status: SkillStatus): string {
    return SKILL_STATUS_META[status].label;
  }

  protected statusTone(status: SkillStatus): string {
    return `sp-badge-${SKILL_STATUS_META[status].tone}`;
  }

  protected priorityLabel(priority: SkillPriority): string {
    return SKILL_PRIORITY_META[priority].label;
  }

  protected priorityTone(priority: SkillPriority): string {
    return `sp-badge-${SKILL_PRIORITY_META[priority].tone}`;
  }

  protected gapLabel(status: SkillStatus): string {
    return status === 'acquise' ? 'None' : status === 'en_cours' ? 'Closing' : 'Open';
  }

  protected actionLabel(skill: SkillComparison): string {
    if (skill.statut === 'acquise') return 'Already satisfied by your profile.';
    if (!skill.formations_recommandees.length) {
      return 'No training in the catalogue covers this skill yet.';
    }
    return skill.formations_recommandees.map(humanizeIdentifier).join(' · ');
  }

  protected displayName(value: string): string {
    return humanizeIdentifier(value);
  }

  private load(selection: CareerSelection): void {
    this.selection.set(selection);
    this.loading.set(true);
    this.error.set('');
    this.requiredLevel.set(null);
    this.career
      .getRequiredLevel(selection.metier)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({ next: level => this.requiredLevel.set(level) });
    this.career
      .getSkillGap(selection.profil, selection.metier)
      .pipe(
        finalize(() => this.loading.set(false)),
        takeUntilDestroyed(this.destroyRef)
      )
      .subscribe({
        next: report => {
          this.report.set(report);
          this.activeTab.set('all');
        },
        error: error => {
          this.report.set(null);
          this.error.set(
            apiErrorMessage(
              error,
              'The skill gap analysis could not be produced. Check that the backend and Fuseki are running, then try again.'
            )
          );
        }
      });
  }
}

function countStatus(report: SkillGapReport, status: SkillStatus): number {
  return report.competences.filter(skill => skill.statut === status).length;
}

function sortSkills(skills: SkillComparison[]): SkillComparison[] {
  return [...skills].sort((a, b) => {
    const byStatus = STATUS_ORDER[a.statut] - STATUS_ORDER[b.statut];
    if (byStatus !== 0) return byStatus;
    const byPriority = PRIORITY_ORDER[a.priorite] - PRIORITY_ORDER[b.priorite];
    if (byPriority !== 0) return byPriority;
    return a.label.localeCompare(b.label);
  });
}

function coverageNote(skill: SkillComparison): string {
  if (skill.statut === 'acquise') return 'Declared as acquired in your profile.';
  const courses = skill.formations_recommandees.length;
  if (skill.statut === 'en_cours') {
    return `${courses} training${courses === 1 ? '' : 's'} in your profile already teach this skill.`;
  }
  return courses
    ? `${courses} catalogue training${courses === 1 ? '' : 's'} can close this gap.`
    : 'No catalogue training covers this skill yet.';
}
