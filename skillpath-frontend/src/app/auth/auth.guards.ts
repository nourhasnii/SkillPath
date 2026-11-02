import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map, of, switchMap } from 'rxjs';
import {
  AccountRole,
  AuthService,
  dashboardForRole,
  profileNeedsOnboarding
} from './auth.service';

export const authGuard: CanActivateFn = (_route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const currentUser = auth.currentUser();
  if (currentUser) return true;

  return auth.restoreSession().pipe(map(user => user
    ? true
    : router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } })
  ));
};

export const profileCompletionGuard: CanActivateFn = (route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  const user = auth.currentUser();
  const profile$ = user ? auth.getProfile() : auth.restoreSession().pipe(switchMap(currentUser => {
    if (!currentUser) {
      return of(router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } }));
    }
    return auth.getProfile();
  }));

  return profile$.pipe(map(profile => {
    if (profile && typeof profile !== 'string' && 'role' in profile && 'profile' in profile) {
      if (profile.role === 'ADMIN') return true;
      if (route.data['requireProfileCompletion'] === true && profileNeedsOnboarding(profile.role, profile)) {
        return router.parseUrl(`/${profile.role.toLowerCase()}/onboarding`);
      }
      return true;
    }
    return profile ?? router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
  }));
};

export const roleGuard: CanActivateFn = (route, state) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const currentUser = auth.currentUser();

  if (!currentUser) {
    return auth.restoreSession().pipe(map(user => {
      if (!user) {
        return router.createUrlTree(['/login'], { queryParams: { returnUrl: state.url } });
      }
      return allowedForRole(user.role, route.data['roles'])
        ? true
        : router.parseUrl(dashboardForRole(user.role));
    }));
  }

  return allowedForRole(currentUser.role, route.data['roles'])
    ? true
    : router.parseUrl(dashboardForRole(currentUser.role));
};

function allowedForRole(role: AccountRole, allowed: unknown): boolean {
  return Array.isArray(allowed) && allowed.includes(role);
}
