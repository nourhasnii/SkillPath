import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import {
  ActivatedRouteSnapshot,
  NavigationEnd,
  Router,
  RouterLink,
  RouterLinkActive,
  RouterOutlet
} from '@angular/router';
import { filter } from 'rxjs';

import { AuthService, dashboardForRole } from '../auth/auth.service';
import { CareerService } from './career.service';
import { IconComponent } from './icon.component';

interface NavItem {
  path: string;
  label: string;
  icon: string;
  exact?: boolean;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

interface NotificationItem {
  id: string;
  title: string;
  detail: string;
  link: string;
}

/**
 * Persistent workspace shell for authenticated pages.
 * Sidebar + top bar + routed content, with breadcrumbs, active indicators and a
 * collapsible drawer below 1080px.
 */
@Component({
  selector: 'app-career-shell',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, FormsModule, IconComponent],
  templateUrl: './career-shell.component.html',
  styleUrl: './career-shell.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class CareerShellComponent implements OnInit {
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);
  private readonly career = inject(CareerService);
  private readonly destroyRef = inject(DestroyRef);

  readonly user = this.auth.currentUser;
  readonly context = this.career.context;

  private readonly pageTitleState = signal('Career overview');
  private readonly pageSubtitleState = signal('');

  readonly pageTitle = this.pageTitleState.asReadonly();
  readonly pageSubtitle = this.pageSubtitleState.asReadonly();

  readonly sidebarOpen = signal(false);
  readonly searchTerm = signal('');
  readonly notificationsOpen = signal(false);
  readonly menuOpen = signal(false);
  readonly signingOut = signal(false);

  readonly notifications = computed<NotificationItem[]>(() => {
    // Personal reminders point at student/professional pages (/account/profile,
    // /learning-path) that Admin cannot open: never surface dead links for Admin.
    if (this.user()?.role === 'ADMIN') return [];

    const context = this.context();
    if (!context) return [];
    const items: NotificationItem[] = [];

    if (!context.targetOccupation) {
      items.push({
        id: 'target',
        title: 'Choose your target occupation',
        detail: 'The skill gap analysis and learning path both compare you against one occupation.',
        link: '/account/profile'
      });
    } else if (context.profileCompletion < 100) {
      items.push({
        id: 'profile',
        title: `Your profile is ${context.profileCompletion}% complete`,
        detail: 'Add the missing details so the analysis reflects your real background.',
        link: '/account/profile'
      });
    }

    for (const path of context.savedPaths) {
      const remaining = path.formations.filter(
        training => !context.followedTrainings.includes(training.id)
      );
      if (remaining.length) {
        items.push({
          id: `path-${path.id}`,
          title: `${remaining.length} training${remaining.length > 1 ? 's' : ''} left in “${path.label}”`,
          detail: 'Open your learning path to mark a training as completed.',
          link: '/learning-path'
        });
      }
    }

    return items;
  });

  readonly initials = computed(() => {
    const name = this.user()?.full_name?.trim();
    if (!name) return 'SP';
    return name
      .split(/\s+/)
      .slice(0, 2)
      .map(part => part.charAt(0).toUpperCase())
      .join('');
  });

  readonly navigationGroups = computed<NavGroup[]>(() => {
    if (this.user()?.role === 'ADMIN') {
      return [
        {
          label: 'Overview',
          items: [
            { path: '/dashboard', label: 'Dashboard', icon: 'grid', exact: true },
            { path: '/knowledge-graph', label: 'Knowledge Graph', icon: 'graph', exact: true }
          ]
        },
        {
          label: 'Knowledge management',
          items: [
            { path: '/dashboard/competences', label: 'Competences', icon: 'sparkle' },
            { path: '/dashboard/occupations', label: 'Occupations', icon: 'target' },
            { path: '/dashboard/families', label: 'Occupation families', icon: 'grid' },
            { path: '/dashboard/levels', label: 'Levels', icon: 'layers' },
            { path: '/dashboard/trainings', label: 'Trainings', icon: 'path' },
            { path: '/dashboard/modules', label: 'Modules', icon: 'layers' }
          ]
        },
        {
          label: 'User management',
          items: [
            { path: '/dashboard/profiles', label: 'Profiles', icon: 'user' },
            { path: '/dashboard/evaluations', label: 'Evaluations', icon: 'check' },
            { path: '/dashboard/users', label: 'User accounts', icon: 'user' }
          ]
        },
        {
          label: 'Intelligence',
          items: [
            { path: '/dashboard/parcours', label: 'Parcours', icon: 'path' },
            { path: '/dashboard/generated-paths', label: 'Generated paths history', icon: 'refresh' },
            { path: '/dashboard/redundant-competencies', label: 'Redundant competencies', icon: 'refresh' },
            { path: '/dashboard/shared-competencies', label: 'Shared competencies between occupations', icon: 'graph' },
            { path: '/dashboard/untaught-competencies', label: 'Untaught competencies', icon: 'target' },
            { path: '/semantic-assistant', label: 'Semantic Assistant', icon: 'sparkle' }
          ]
        }
      ];
    }

    return [
      {
        label: 'Workspace',
        items: [
          { path: '/career', label: 'Dashboard', icon: 'grid', exact: true },
          { path: '/skill-gap', label: 'Skill Gap Analysis', icon: 'target', exact: true },
          { path: '/learning-path', label: 'Personalised Learning Path', icon: 'path', exact: true },
          { path: '/parcours-optimal', label: 'Parcours optimal', icon: 'compass', exact: true },
          { path: '/career-bridges', label: 'Career bridges', icon: 'branch', exact: true },
          { path: '/evaluations', label: 'My Evaluations', icon: 'check', exact: true },
          { path: '/catalogue', label: 'Catalogue', icon: 'book' }
        ]
      },
      {
        label: 'Insights',
        items: [
          { path: '/knowledge-graph', label: 'Knowledge Graph', icon: 'graph', exact: true },
          { path: '/semantic-assistant', label: 'Semantic Assistant', icon: 'sparkle' }
        ]
      },
      {
        label: 'Account',
        items: [{ path: '/account/profile', label: 'Profile', icon: 'user', exact: true }]
      }
    ];
  });

  ngOnInit(): void {
    this.syncPageMeta();
    this.router.events
      .pipe(filter(event => event instanceof NavigationEnd), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.syncPageMeta());

    this.career.loadContext().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({ error: () => undefined });
  }

  protected profileRoute(): string {
    return this.user()?.role === 'ADMIN' ? dashboardForRole('ADMIN') : '/account/profile';
  }

  protected profileLabel(): string {
    return this.user()?.role === 'ADMIN' ? 'Admin dashboard' : 'Profile';
  }

  protected toggleSidebar(): void {
    this.sidebarOpen.update(open => !open);
    this.closePanels();
  }

  protected closeSidebar(): void {
    this.sidebarOpen.set(false);
  }

  protected toggleNotifications(): void {
    this.notificationsOpen.update(open => !open);
    this.menuOpen.set(false);
  }

  protected toggleMenu(): void {
    this.menuOpen.update(open => !open);
    this.notificationsOpen.set(false);
  }

  protected closePanels(): void {
    this.notificationsOpen.set(false);
    this.menuOpen.set(false);
  }

  protected submitSearch(): void {
    const term = this.searchTerm().trim();
    if (!term) return;
    this.closeSidebar();
    this.closePanels();
    this.router.navigate(['/knowledge-graph'], { queryParams: { q: term } });
  }

  protected signOut(): void {
    if (this.signingOut()) return;
    this.signingOut.set(true);
    this.auth.logout().subscribe({
      next: () => this.router.navigate(['/login']),
      error: () => {
        this.signingOut.set(false);
        this.router.navigate(['/login']);
      }
    });
  }

  private syncPageMeta(): void {
    const routeData: Record<string, unknown>[] = [];
    let route: ActivatedRouteSnapshot | null = this.router.routerState.snapshot.root;
    while (route !== null) {
      routeData.push(route.data ?? {});
      route = route.firstChild;
    }
    const data = [...routeData].reverse().find(item => typeof item['title'] === 'string')
      ?? routeData.at(-1)
      ?? {};
    this.pageTitleState.set(
      typeof data['title'] === 'string' ? data['title'] : 'Career overview'
    );
    this.pageSubtitleState.set(typeof data['subtitle'] === 'string' ? data['subtitle'] : '');
    this.closeSidebar();
    this.closePanels();
  }
}
