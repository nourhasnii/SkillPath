import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, HostListener, inject, OnInit, signal, WritableSignal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { catchError, finalize, forkJoin, of } from 'rxjs';
import {
  apiErrorMessage,
  DashboardDataService,
  DashboardStats,
  CatalogueTraining,
  displayEntityName,
  EntityListItem,
  GraphSnapshot,
  PublicDashboardStats
} from './dashboard/dashboard-data.service';

interface FeatureSlide {
  eyebrow: string;
  title: string;
  description: string;
  kind: 'skills' | 'gap' | 'prerequisite' | 'path' | 'graph';
}

@Component({
  selector: 'app-landing-page',
  imports: [RouterLink],
  templateUrl: './landing-page.html',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class LandingPage implements OnInit {
  private readonly data = inject(DashboardDataService);
  private pendingLists = 5;

  protected readonly menuOpen = signal(false);
  protected readonly activeFeature = signal(0);
  protected readonly selectedGraphNode = signal('');
  protected readonly stats = signal<DashboardStats | null>(null);
  protected readonly cataloguePreview = signal<{
    stats: PublicDashboardStats;
    trainings: CatalogueTraining[];
  } | null>(null);
  protected readonly statsLoading = signal(true);
  protected readonly statsError = signal('');
  protected readonly repositoryLoading = signal(true);
  protected readonly repositoryError = signal('');
  protected readonly graph = signal<GraphSnapshot | null>(null);
  protected readonly graphLoading = signal(true);
  protected readonly graphError = signal('');
  protected readonly competences = signal<EntityListItem[]>([]);
  protected readonly occupations = signal<EntityListItem[]>([]);
  protected readonly trainings = signal<EntityListItem[]>([]);
  protected readonly profiles = signal<EntityListItem[]>([]);
  protected readonly paths = signal<EntityListItem[]>([]);
  protected readonly displayName = displayEntityName;

  protected readonly features: FeatureSlide[] = [
    { eyebrow: '01 / Skill intelligence', title: 'Understand what you already know.', description: 'Turn a profile into a living map of validated capability.', kind: 'skills' },
    { eyebrow: '02 / Skill gap analysis', title: 'See what stands between you and a target role.', description: 'Compare your skills with the requirements of a target role.', kind: 'gap' },
    { eyebrow: '03 / Prerequisite reasoning', title: 'Understand which skills should come first.', description: 'Explore how trainings connect through prerequisites.', kind: 'prerequisite' },
    { eyebrow: '04 / Learning path', title: 'Turn missing skills into a structured path.', description: 'Review the learning paths you have saved.', kind: 'path' },
    { eyebrow: '05 / Knowledge graph', title: 'Explore how everything connects.', description: 'See how profiles, skills and trainings link together.', kind: 'graph' }
  ];

  protected readonly featureItems = computed<EntityListItem[]>(() => {
    switch (this.features[this.activeFeature()].kind) {
      case 'skills': return this.competences();
      case 'gap': return this.occupations();
      case 'prerequisite': return this.trainings();
      case 'path': return this.paths();
      case 'graph': return this.graph()?.nodes ?? [];
    }
  });

  protected readonly featureItemsTitle = computed(() => {
    switch (this.features[this.activeFeature()].kind) {
      case 'skills': return 'Skills in the repository';
      case 'gap': return 'Occupations in the repository';
      case 'prerequisite': return 'Trainings in the repository';
      case 'path': return 'Saved learning paths';
      case 'graph': return 'Connections in the knowledge graph';
    }
  });

  protected readonly graphNodes = computed(() => this.graph()?.nodes.slice(0, 8) ?? []);
  protected readonly graphEdgeCount = computed(() => this.graph()?.edges.length ?? 0);

  ngOnInit(): void {
    forkJoin({
      stats: this.data.getPublicDashboard(),
      trainings: this.data.getPublicCatalogue()
    }).pipe(
      catchError(() => of(null))
    ).subscribe(result => {
      if (!result || result.trainings.length < 3) return;
      this.cataloguePreview.set({
        stats: result.stats,
        trainings: [...result.trainings]
          .sort((left, right) => left.nom.localeCompare(right.nom))
          .slice(0, 4)
      });
    });

    this.data.getStats().subscribe({
      next: stats => {
        this.stats.set(stats);
        this.statsLoading.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.statsError.set(apiErrorMessage(error, 'Repository statistics could not be loaded.'));
        this.statsLoading.set(false);
      }
    });

    this.data.getGraph().subscribe({
      next: graph => {
        this.graph.set(graph);
        this.graphLoading.set(false);
      },
      error: (error: HttpErrorResponse) => {
        this.graphError.set(apiErrorMessage(error, 'The knowledge graph could not be loaded.'));
        this.graphLoading.set(false);
      }
    });

    this.loadList('Competence', this.competences);
    this.loadList('Metier', this.occupations);
    this.loadList('Formation', this.trainings);
    this.loadList('ProfilUtilisateur', this.profiles);
    this.loadList('Parcours', this.paths);
  }

  protected nextFeature(): void {
    this.activeFeature.update(index => (index + 1) % this.features.length);
  }

  protected previousFeature(): void {
    this.activeFeature.update(index => (index - 1 + this.features.length) % this.features.length);
  }

  protected setFeature(index: number): void {
    this.activeFeature.set(index);
  }

  protected entityEdges(id: string): number {
    return this.graph()?.edges.filter(edge => edge.from === id || edge.to === id).length ?? 0;
  }

  protected trainingType(training: CatalogueTraining): string {
    switch (training.type) {
      case 'FormationEnLigne': return 'Online';
      case 'FormationPresentielle': return 'On-site';
      default: return 'Training';
    }
  }

  protected scrollTo(id: string): void {
    this.menuOpen.set(false);
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' });
  }

  protected toggleMenu(): void {
    this.menuOpen.update(open => !open);
  }

  protected closeMenu(): void {
    this.menuOpen.set(false);
  }

  protected setGraphNode(id: string): void {
    this.selectedGraphNode.set(id);
  }

  @HostListener('window:keydown', ['$event'])
  protected handleKeydown(event: KeyboardEvent): void {
    if (event.key === 'ArrowRight') this.nextFeature();
    if (event.key === 'ArrowLeft') this.previousFeature();
    if (event.key === 'Escape') this.closeMenu();
  }

  private loadList(
    kind: 'Competence' | 'Metier' | 'Formation' | 'ProfilUtilisateur' | 'Parcours',
    target: WritableSignal<EntityListItem[]>
  ): void {
    this.data.getList(kind).pipe(finalize(() => this.finishListLoad())).subscribe({
      next: items => target.set(items),
      error: (error: HttpErrorResponse) => {
        this.repositoryError.set(apiErrorMessage(error, 'Repository entities could not be loaded.'));
      }
    });
  }

  private finishListLoad(): void {
    this.pendingLists--;
    if (this.pendingLists === 0) this.repositoryLoading.set(false);
  }
}
