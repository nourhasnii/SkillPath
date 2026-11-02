import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, OnInit, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AuthService } from '../auth/auth.service';
import { IconComponent } from '../career/icon.component';
import {
  apiErrorMessage,
  DashboardDataService,
  DashboardStats
} from './dashboard-data.service';
import { KnowledgeAnalyticsComponent } from './knowledge-analytics.component';

interface KpiCard {
  label: string;
  detail: string;
  value: number;
  icon: string;
  tone: 'purple' | 'blue' | 'orange' | 'green';
  path: string;
}

interface QuickAction {
  label: string;
  detail: string;
  icon: string;
  path: string;
}

type RepositoryStatus = 'checking' | 'online' | 'offline';

/**
 * Administration home: welcome, live KPI cards from the ontology counts,
 * shortcuts and the Knowledge Analytics section.
 */
@Component({
  selector: 'app-dashboard-home',
  standalone: true,
  imports: [RouterLink, IconComponent, KnowledgeAnalyticsComponent],
  templateUrl: './dashboard-home.component.html',
  styleUrl: './dashboard-home.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class DashboardHomeComponent implements OnInit {
  private readonly data = inject(DashboardDataService);
  private readonly auth = inject(AuthService);

  protected readonly stats = signal<DashboardStats | null>(null);
  protected readonly loading = signal(true);
  protected readonly errorMessage = signal('');

  protected readonly adminName = computed(
    () => this.auth.currentUser()?.full_name?.trim() || 'Admin'
  );

  protected readonly greeting = computed(() => {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 18) return 'Good afternoon';
    return 'Good evening';
  });

  /**
   * Derived from the real API outcome: the repository is only reported as
   * connected once the statistics actually came back from Fuseki.
   */
  protected readonly repositoryStatus = computed<RepositoryStatus>(() => {
    if (this.loading()) return 'checking';
    return this.errorMessage() ? 'offline' : 'online';
  });

  protected readonly statusLabel = computed(() => {
    switch (this.repositoryStatus()) {
      case 'checking': return 'Checking repository…';
      case 'offline': return 'Repository unreachable';
      default: return 'Repository connected';
    }
  });

  protected readonly kpis = computed<KpiCard[]>(() => {
    const totals = this.stats();
    if (!totals) return [];
    return [
      {
        label: 'Total competencies',
        detail: 'Skills declared in the ontology',
        value: totals.competences,
        icon: 'sparkle',
        tone: 'purple',
        path: '/dashboard/competences'
      },
      {
        label: 'Total occupations',
        detail: 'Job profiles mapped to skills',
        value: totals.metiers,
        icon: 'briefcase',
        tone: 'blue',
        path: '/dashboard/occupations'
      },
      {
        label: 'Total trainings',
        detail: 'Catalogue entries with prerequisites',
        value: totals.formations,
        icon: 'graduation',
        tone: 'orange',
        path: '/dashboard/trainings'
      },
      {
        label: 'Total profiles',
        detail: 'Learners and professionals',
        value: totals.profils,
        icon: 'user',
        tone: 'green',
        path: '/dashboard/profiles'
      }
    ];
  });

  protected readonly quickActions: QuickAction[] = [
    { label: 'Manage Competencies', detail: 'Create, edit and link skills', icon: 'sparkle', path: '/dashboard/competences' },
    { label: 'Manage Occupations', detail: 'Job profiles and required skills', icon: 'briefcase', path: '/dashboard/occupations' },
    { label: 'Manage Trainings', detail: 'Catalogue, prerequisites, modules', icon: 'graduation', path: '/dashboard/trainings' },
    { label: 'Manage Profiles', detail: 'Learner and professional profiles', icon: 'user', path: '/dashboard/profiles' },
    { label: 'Manage Evaluations', detail: 'Technical and behavioural records', icon: 'check', path: '/dashboard/evaluations' },
    { label: 'Explore Knowledge Graph', detail: 'Browse the ontology network', icon: 'graph', path: '/knowledge-graph' }
  ];

  ngOnInit(): void {
    this.load();
  }

  protected retry(): void {
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.errorMessage.set('');
    this.data.getStats().subscribe({
      next: stats => {
        this.stats.set(stats);
        this.loading.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.errorMessage.set(apiErrorMessage(error, 'Dashboard statistics could not be loaded.'));
        this.stats.set(null);
        this.loading.set(false);
      }
    });
  }
}
