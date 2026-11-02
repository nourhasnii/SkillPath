import { TestBed } from '@angular/core/testing';
import {
  GuardResult,
  MaybeAsync,
  provideRouter,
  Router,
  UrlTree
} from '@angular/router';
import { firstValueFrom, isObservable, of } from 'rxjs';
import { AuthService, AuthUser } from './auth.service';
import { authGuard, roleGuard } from './auth.guards';
import { routes } from '../app.routes';

const student: AuthUser = {
  id: 'account-1',
  email: 'student@example.test',
  full_name: 'Test Student',
  role: 'STUDENT',
  profile_iri: 'profil_test',
  experience: ''
};

async function asUrlTree(result: MaybeAsync<GuardResult>): Promise<UrlTree> {
  const destination = isObservable(result) ? await firstValueFrom(result) : await result;
  if (!(destination instanceof UrlTree)) throw new Error('Expected the guard to return a URL tree.');
  return destination;
}

describe('authentication route guards', () => {
  const setup = (user: AuthUser | null) => {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([]),
        {
          provide: AuthService,
          useValue: {
            currentUser: vi.fn(() => user),
            restoreSession: vi.fn(() => of(user))
          }
        }
      ]
    });
    return TestBed.inject(Router);
  };

  it('redirects an unauthenticated visitor to login with a return URL', async () => {
    const router = setup(null);
    const state = Object.assign(router.routerState.snapshot, { url: '/account/profile' });
    const destination = await asUrlTree(TestBed.runInInjectionContext(() =>
      authGuard(router.routerState.snapshot.root, state)
    ));

    expect(router.serializeUrl(destination))
      .toContain('/login?returnUrl=%2Faccount%2Fprofile');
  });

  it('redirects a student away from an admin-only route', async () => {
    const router = setup(student);
    const route = Object.assign(router.routerState.snapshot.root, { data: { roles: ['ADMIN'] } });
    const destination = await asUrlTree(TestBed.runInInjectionContext(() =>
      roleGuard(route, router.routerState.snapshot)
    ));

    expect(router.serializeUrl(destination))
      .toBe('/student/dashboard');
  });

  it.each(['skill-gap', 'learning-path', 'parcours-optimal', 'career-bridges'])(
    'redirects an admin away from the personal page /%s',
    async segment => {
      const workspace = routes.find(route => route.path === '' && !!route.children);
      const personalPage = workspace?.children?.find(route => route.path === segment);
      const admin: AuthUser = { ...student, role: 'ADMIN', profile_iri: 'profil_admin' };
      const router = setup(admin);
      const route = Object.assign(router.routerState.snapshot.root, {
        data: personalPage?.data
      });
      const destination = await asUrlTree(TestBed.runInInjectionContext(() =>
        roleGuard(route, router.routerState.snapshot)
      ));

      expect(router.serializeUrl(destination)).toBe('/dashboard');
    }
  );

  it.each(['STUDENT', 'PROFESSIONAL'] as const)(
    'allows %s users through the guarded career workspace',
    role => {
      const user: AuthUser = {
        ...student,
        role,
        profile_iri: `profil_${role.toLowerCase()}`
      };
      const router = setup(user);
      const workspace = routes.find(route => route.path === '' && !!route.children);
      if (!workspace) throw new Error('Expected the guarded career workspace route.');
      const activatedRoute = Object.assign(router.routerState.snapshot.root, {
        data: workspace.data
      });

      expect(TestBed.runInInjectionContext(() =>
        roleGuard(activatedRoute, router.routerState.snapshot)
      )).toBe(true);
    }
  );

  it.each(['STUDENT', 'PROFESSIONAL'] as const)(
    'allows %s users through the career-bridges page guard',
    role => {
      const user: AuthUser = {
        ...student,
        role,
        profile_iri: `profil_${role.toLowerCase()}`
      };
      const router = setup(user);
      const workspace = routes.find(route => route.path === '' && !!route.children);
      const careerBridges = workspace?.children?.find(route => route.path === 'career-bridges');
      if (!careerBridges) throw new Error('Expected the guarded career-bridges route.');
      const activatedRoute = Object.assign(router.routerState.snapshot.root, {
        data: careerBridges.data
      });

      expect(TestBed.runInInjectionContext(() =>
        roleGuard(activatedRoute, router.routerState.snapshot)
      )).toBe(true);
    }
  );
});
