import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router, ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';
import { authGuard, profileCompletionGuard, roleGuard } from './auth.guards';
import { isSessionProtectedRoute } from './auth-error.interceptor';
import { routes } from '../app.routes';
import { AuthService, destinationAfterLogin } from './auth.service';
import { AccountProfileComponent } from '../dashboard/account-profile.component';
import { DashboardLayoutComponent } from '../dashboard/dashboard-layout.component';
import { ProfileOnboardingComponent } from '../dashboard/profile-onboarding.component';
import { DashboardDataService } from '../dashboard/dashboard-data.service';
import { LearningPathComponent } from '../pages/learning-path/learning-path.component';
import { ParcoursOptimalComponent } from '../pages/parcours-optimal/parcours-optimal.component';
import { humanizeIdentifier } from '../career/career.service';

describe('public and protected navigation', () => {
  it('formats ontology identifiers as labels without altering submitted identifiers', () => {
    expect(humanizeIdentifier('met_DataScientist')).toBe('Data Scientist');
    expect(humanizeIdentifier('comp_Python')).toBe('Python');
    expect(humanizeIdentifier('_comp_Communication')).toBe('Communication');
  });

  it('keeps the landing page and authentication pages public', () => {
    const landing = routes.find(route => route.path === '');
    const login = routes.find(route => route.path === 'login');
    const register = routes.find(route => route.path === 'register');

    expect(landing?.canActivate).toBeUndefined();
    expect(login?.canActivate).toBeUndefined();
    expect(register?.canActivate).toBeUndefined();
  });

  it('guards the shared shell and keeps personalized and optimal paths separate', () => {
    const workspace = routes.find(route => route.path === '' && !!route.children);
    expect(workspace?.canActivate).toContain(authGuard);
    expect(workspace?.canActivate).toContain(roleGuard);
    expect(workspace?.data?.['roles']).toEqual(['STUDENT', 'PROFESSIONAL', 'ADMIN']);

    const paths = (workspace?.children ?? []).map(child => child.path);
    expect(paths).toContain('career');
    expect(paths).toContain('skill-gap');
    expect(paths).toContain('learning-path');
    expect(paths).toContain('parcours-optimal');
    expect(paths).toContain('catalogue');
    expect(paths).toContain('knowledge-graph');
    expect(paths).toContain('account/profile');
    expect(paths).toContain('dashboard');
    const skillGapRoute = workspace?.children?.find(child => child.path === 'skill-gap');
    expect(skillGapRoute?.canActivate).toContain(roleGuard);
    expect(skillGapRoute?.canActivate).toContain(profileCompletionGuard);
    expect(skillGapRoute?.data?.['roles']).toEqual(['STUDENT', 'PROFESSIONAL']);
    expect(skillGapRoute?.data?.['title']).toBe('Skill Gap Analysis');
    const learningPathRoute = workspace?.children?.find(child => child.path === 'learning-path');
    expect(learningPathRoute?.component).toBe(LearningPathComponent);
    expect(learningPathRoute?.data?.['title']).toBe('Personalised Learning Path');
    expect(learningPathRoute?.canActivate).toContain(roleGuard);
    expect(learningPathRoute?.canActivate).toContain(profileCompletionGuard);
    expect(learningPathRoute?.data?.['roles']).toEqual(['STUDENT', 'PROFESSIONAL']);
    const optimalPathRoute = workspace?.children?.find(child => child.path === 'parcours-optimal');
    expect(optimalPathRoute?.component).toBe(ParcoursOptimalComponent);
    expect(optimalPathRoute?.canActivate).toContain(roleGuard);
    expect(optimalPathRoute?.data?.['roles']).toEqual(['STUDENT', 'PROFESSIONAL']);
    expect(optimalPathRoute?.data?.['title']).toBe('Parcours optimal');
    const catalogueRoute = workspace?.children?.find(child => child.path === 'catalogue');
    expect(catalogueRoute?.canActivate).toContain(roleGuard);
    expect(catalogueRoute?.data?.['roles']).toEqual(['STUDENT', 'PROFESSIONAL']);
    expect(catalogueRoute?.data?.['title']).toBe('Catalogue');
    const catalogueDetailRoute = workspace?.children?.find(child => child.path === 'catalogue/:id');
    expect(catalogueDetailRoute?.component).toBe(catalogueRoute?.component);
    expect(catalogueDetailRoute?.canActivate).toContain(roleGuard);
    expect(catalogueDetailRoute?.data?.['roles']).toEqual(['STUDENT', 'PROFESSIONAL']);
    const profileRoute = workspace?.children?.find(child => child.path === 'account/profile');
    expect(profileRoute?.component).toBe(AccountProfileComponent);
    expect(profileRoute?.canActivate).toContain(roleGuard);
    expect(profileRoute?.data?.['roles']).toEqual(['STUDENT', 'PROFESSIONAL']);
    expect(profileRoute?.canActivate).not.toContain(profileCompletionGuard);
    const dashboard = workspace?.children?.find(child => child.path === 'dashboard');
    expect(dashboard?.component).toBe(DashboardLayoutComponent);
    expect(dashboard?.data?.['roles']).toContain('ADMIN');
  });

  it('keeps admin URLs and onboarding routes intact under the shared shell', () => {
    const workspace = routes.find(route => route.path === '' && !!route.children);
    const dashboard = workspace?.children?.find(route => route.path === 'dashboard');
    expect((dashboard?.children ?? []).map(child => child.path)).toContain('users');
    expect((dashboard?.children ?? []).map(child => child.path)).toContain('shared-competencies');

    const onboarding = routes.find(route => route.path === 'student/onboarding');
    expect(onboarding?.canActivate).toContain(authGuard);
    expect(onboarding?.data?.['roles']).toEqual(['STUDENT']);

    expect(routes.find(route => route.path === 'account/profile')).toBeUndefined();
  });

  it('always sends administrators to the full dashboard after login', () => {
    expect(destinationAfterLogin('ADMIN', '/dashboard/users')).toBe('/dashboard');
    expect(destinationAfterLogin('ADMIN', '/student/dashboard')).toBe('/dashboard');
  });

  it('preserves safe return URLs for student and professional accounts', () => {
    expect(destinationAfterLogin('STUDENT', '/account/profile')).toBe('/account/profile');
    expect(destinationAfterLogin('STUDENT', '/catalogue')).toBe('/catalogue');
    expect(destinationAfterLogin('PROFESSIONAL', '/catalogue/form_intro')).toBe('/catalogue/form_intro');
    expect(destinationAfterLogin('PROFESSIONAL', '//outside.test')).toBe('/professional/dashboard');
    expect(destinationAfterLogin('STUDENT', null)).toBe('/student/dashboard');
  });

  it('does not redirect to login after an expired API request on the public landing or auth pages', () => {
    expect(isSessionProtectedRoute('/')).toBe(false);
    expect(isSessionProtectedRoute('/login')).toBe(false);
    expect(isSessionProtectedRoute('/register')).toBe(false);
    expect(isSessionProtectedRoute('/forgot-password')).toBe(false);
  });

  it('recognizes session-protected dashboard and analysis paths', () => {
    expect(isSessionProtectedRoute('/dashboard')).toBe(true);
    expect(isSessionProtectedRoute('/dashboard/competences')).toBe(true);
    expect(isSessionProtectedRoute('/skill-gap')).toBe(true);
    expect(isSessionProtectedRoute('/learning-path')).toBe(true);
    expect(isSessionProtectedRoute('/parcours-optimal')).toBe(true);
    expect(isSessionProtectedRoute('/catalogue')).toBe(true);
  });

  it('only navigates to the success screen after the backend confirms a complete profile', async () => {
    await TestBed.configureTestingModule({
      imports: [ProfileOnboardingComponent],
      providers: [
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { url: [{ path: 'student' }] }
          }
        },
        {
          provide: DashboardDataService,
          useValue: {
            getList: vi.fn(() => of([]))
          }
        },
        {
          provide: AuthService,
          useValue: {
            currentUser: signal(null),
            getProfile: vi.fn(() => of({
              id: 'user-1',
              email: 'student@example.test',
              full_name: 'Ada Lovelace',
              role: 'STUDENT',
              profile_iri: 'profil_123',
              experience: '',
              profile: {
                id: 'profil_123',
                type: 'ProfilUtilisateur',
                class: 'ProfilEtudiant',
                label: 'Ada Lovelace',
                properties: {},
                relations: {
                  vise: [{ id: 'metier_1', label: 'Data Analyst' }],
                  aAcquis: [{ id: 'comp_1', label: 'Python' }]
                }
              }
            })),
            saveProfile: vi.fn(() => of({
              id: 'user-1',
              email: 'student@example.test',
              full_name: 'Ada Lovelace',
              role: 'STUDENT',
              profile_iri: 'profil_123',
              experience: ''
            }))
          }
        }
      ]
    }).compileComponents();

    const router = TestBed.inject(Router);
    const fixture = TestBed.createComponent(ProfileOnboardingComponent);
    const component = fixture.componentInstance as any;
    const navigateSpy = vi.spyOn(router, 'navigateByUrl');

    component.fullName.set('Ada Lovelace');
    component.experience.set('');
    component.targetOccupation.set('metier_1');
    component.acquiredCompetences.set(['comp_1']);

    component.saveProfile();

    expect(navigateSpy).toHaveBeenCalledWith('/student/profile-success');
  });

  it('requires a professional background and only completes onboarding once persisted', async () => {
    const professionalProfile = {
      id: 'user-2',
      email: 'professional@example.test',
      full_name: 'Grace Hopper',
      role: 'PROFESSIONAL',
      profile_iri: 'profil_pro',
      experience: 'Ten years in software engineering',
      profile: {
        id: 'profil_pro',
        type: 'ProfilUtilisateur',
        class: 'ProfilProfessionnel',
        label: 'Grace Hopper',
        properties: {},
        relations: {
          vise: [{ id: 'metier_1', label: 'Data Engineer' }],
          aAcquis: [{ id: 'comp_1', label: 'Python' }]
        }
      }
    };

    await TestBed.configureTestingModule({
      imports: [ProfileOnboardingComponent],
      providers: [
        provideRouter([]),
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: { url: [{ path: 'professional' }] }
          }
        },
        {
          provide: DashboardDataService,
          useValue: {
            getList: vi.fn(() => of([]))
          }
        },
        {
          provide: AuthService,
          useValue: {
            currentUser: signal(null),
            getProfile: vi.fn(() => of(professionalProfile)),
            saveProfile: vi.fn(() => of({
              id: 'user-2',
              email: 'professional@example.test',
              full_name: 'Grace Hopper',
              role: 'PROFESSIONAL',
              profile_iri: 'profil_pro',
              experience: 'Ten years in software engineering'
            }))
          }
        }
      ]
    }).compileComponents();

    const router = TestBed.inject(Router);
    const auth = TestBed.inject(AuthService) as any;
    const fixture = TestBed.createComponent(ProfileOnboardingComponent);
    const component = fixture.componentInstance as any;
    const navigateSpy = vi.spyOn(router, 'navigateByUrl');

    component.role.set('PROFESSIONAL');
    component.fullName.set('Grace Hopper');
    component.targetOccupation.set('metier_1');
    component.acquiredCompetences.set(['comp_1']);

    // Missing professional background: the save is blocked by validation.
    component.experience.set('');
    component.saveProfile();

    expect(auth.saveProfile).not.toHaveBeenCalled();
    expect(component.validationErrors().experience).toBeTruthy();
    expect(component.stepIndex()).toBe(0);

    // Once the background is captured, the persisted profile verifies and onboarding completes.
    component.experience.set('Ten years in software engineering');
    component.saveProfile();

    expect(auth.saveProfile).toHaveBeenCalledTimes(1);
    expect(navigateSpy).toHaveBeenCalledWith('/professional/profile-success');
  });
});
