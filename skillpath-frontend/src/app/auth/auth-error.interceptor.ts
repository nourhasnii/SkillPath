import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';
import { AuthService } from './auth.service';

const publicAuthEndpoints = [
  '/auth/me',
  '/auth/login',
  '/auth/register',
  '/auth/forgot-password',
  '/auth/reset-password'
];

const routesRequiringASession = [
  '/dashboard',
  '/student/dashboard',
  '/professional/dashboard',
  '/account/profile',
  '/career',
  '/skill-gap',
  '/learning-path',
  '/parcours-optimal',
  '/catalogue',
  '/knowledge-graph'
];

export function isSessionProtectedRoute(url: string): boolean {
  return routesRequiringASession.some(route => url === route || url.startsWith(`${route}/`));
}

export const authErrorInterceptor: HttpInterceptorFn = (request, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  return next(request).pipe(catchError((error: unknown) => {
    if (error instanceof HttpErrorResponse
      && error.status === 401
      && isSessionProtectedRoute(router.url.split('?')[0])
      && !publicAuthEndpoints.some(endpoint => request.url.endsWith(endpoint))) {
      auth.expireSession();
      const returnUrl = router.url.startsWith('/login') ? undefined : router.url;
      void router.navigate(['/login'], { queryParams: returnUrl ? { returnUrl } : undefined });
    }
    return throwError(() => error);
  }));
};
