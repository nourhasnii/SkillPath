import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, catchError, of, shareReplay, tap, throwError } from 'rxjs';

export type AccountRole = 'STUDENT' | 'PROFESSIONAL' | 'ADMIN';

export interface AuthUser {
  id: string;
  email: string;
  full_name: string;
  role: AccountRole;
  profile_iri: string | null;
  experience: string;
}

/** Level reference coming from the ontology (`sp:Niveau`). */
export interface LevelInfo {
  id: string;
  label: string;
  value: number | null;
}

export interface AccountProfile extends AuthUser {
  profile: {
    id: string;
    type: string;
    class: string;
    label: string;
    properties: Record<string, string[]>;
    relations: Record<string, ProfileRelatedEntity[]>;
  } | null;
  /** Overall readiness level of the profile (`sp:aPourNiveau`), may be null. */
  level: LevelInfo | null;
  /** Level required by the target occupation (`sp:necessiteNiveau`), may be null. */
  requiredLevel: LevelInfo | null;
}

export interface ProfileRelatedEntity {
  id: string;
  label: string;
  formations?: ProfileRelatedEntity[];
}

export interface RegistrationPayload {
  full_name: string;
  email: string;
  password: string;
  password_confirmation: string;
  profile_type: 'STUDENT' | 'PROFESSIONAL';
}

const API_ROOT = 'http://localhost:8000';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private restoreRequest?: Observable<AuthUser | null>;

  readonly currentUser = signal<AuthUser | null>(null);
  readonly initialized = signal(false);
  readonly authError = signal('');

  restoreSession(): Observable<AuthUser | null> {
    if (this.initialized()) return of(this.currentUser());
    if (this.restoreRequest) return this.restoreRequest;
    this.restoreRequest = this.http.get<AuthUser>(`${API_ROOT}/auth/me`, {
      withCredentials: true
    }).pipe(
      tap(user => {
        this.currentUser.set(user);
        this.initialized.set(true);
        this.authError.set('');
      }),
      catchError((error: HttpErrorResponse) => {
        this.currentUser.set(null);
        this.initialized.set(true);
        this.authError.set(error.status === 401 ? '' : 'The authentication service is unavailable.');
        return of(null);
      }),
      shareReplay({ bufferSize: 1, refCount: false })
    );
    return this.restoreRequest;
  }

  login(email: string, password: string): Observable<AuthUser> {
    return this.http.post<AuthUser>(
      `${API_ROOT}/auth/login`,
      { email, password },
      { withCredentials: true }
    ).pipe(tap(user => this.setAuthenticatedUser(user)));
  }

  register(payload: RegistrationPayload): Observable<AuthUser> {
    return this.http.post<AuthUser>(
      `${API_ROOT}/auth/register`,
      payload,
      { withCredentials: true }
    ).pipe(tap(user => this.setAuthenticatedUser(user)));
  }

  logout(): Observable<void> {
    return this.http.post<void>(
      `${API_ROOT}/auth/logout`,
      {},
      { withCredentials: true }
    ).pipe(tap(() => {
      this.currentUser.set(null);
      this.initialized.set(true);
      this.restoreRequest = undefined;
    }));
  }

  forgotPassword(email: string): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(
      `${API_ROOT}/auth/forgot-password`,
      { email }
    );
  }

  resetPassword(token: string, password: string, passwordConfirmation: string): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(
      `${API_ROOT}/auth/reset-password`,
      { token, password, password_confirmation: passwordConfirmation }
    );
  }

  getProfile(): Observable<AccountProfile> {
    return this.http.get<AccountProfile>(`${API_ROOT}/account/profile`, {
      withCredentials: true
    });
  }

  saveProfile(payload: {
    full_name: string;
    experience: string;
    target_occupation: string;
    acquired_competences: string[];
    completed_trainings: string[];
  }): Observable<AuthUser> {
    return this.http.put<AuthUser>(`${API_ROOT}/account/profile`, payload, {
      withCredentials: true
    }).pipe(tap(user => this.setAuthenticatedUser(user)));
  }

    saveLearningPath(trainings: string[]): Observable<{ id: string; label: string; formations: string[] }> {
      return this.http.post<{ id: string; label: string; formations: string[] }>(
        `${API_ROOT}/account/parcours`,
        { trainings },
        { withCredentials: true }
      );
    }

    updateLearningProgress(pathId: string, completedTrainings: string[]): Observable<{
      path_id: string;
      completed_trainings: string[];
    }> {
      return this.http.put<{ path_id: string; completed_trainings: string[] }>(
        `${API_ROOT}/account/parcours/${encodeURIComponent(pathId)}/progress`,
        { completed_trainings: completedTrainings },
        { withCredentials: true }
      );
    }

  getUsers(): Observable<AuthUser[]> {
    return this.http.get<AuthUser[]>(`${API_ROOT}/admin/users`, {
      withCredentials: true
    });
  }

  updateUserRole(accountId: string, role: AccountRole): Observable<AuthUser> {
    return this.http.put<AuthUser>(
      `${API_ROOT}/admin/users/${encodeURIComponent(accountId)}/role`,
      { role },
      { withCredentials: true }
    );
  }

  setAuthenticatedUser(user: AuthUser): void {
    this.currentUser.set(user);
    this.initialized.set(true);
    this.authError.set('');
    this.restoreRequest = undefined;
  }

  expireSession(): void {
    this.currentUser.set(null);
    this.initialized.set(true);
    this.restoreRequest = undefined;
  }
}

export function dashboardForRole(role: AccountRole): string {
  switch (role) {
    case 'STUDENT': return '/student/dashboard';
    case 'PROFESSIONAL': return '/professional/dashboard';
    case 'ADMIN': return '/dashboard';
  }
}

export function destinationAfterLogin(role: AccountRole, returnUrl: string | null): string {
  if (role === 'ADMIN') return dashboardForRole(role);
  if (
    returnUrl?.startsWith('/')
    && !returnUrl.startsWith('//')
    && !returnUrl.includes('\\')
  ) {
    return returnUrl;
  }
  return dashboardForRole(role);
}

export function profileCompletion(profile: AccountProfile | null | undefined, role?: AccountRole): number {
  const resolvedRole = role ?? profile?.role ?? 'STUDENT';
  const fullName = (profile?.full_name ?? '').trim();
  const experience = (profile?.experience ?? '').trim();
  const targetOccupation = profile?.profile?.relations?.['vise']?.[0]?.id ?? '';
  const acquiredCompetences = profile?.profile?.relations?.['aAcquis'] ?? [];

  const checks = [
    Boolean(fullName),
    Boolean(targetOccupation),
    acquiredCompetences.length > 0,
    resolvedRole === 'PROFESSIONAL' ? Boolean(experience) : true
  ];

  const completed = checks.filter(Boolean).length;
  const total = resolvedRole === 'PROFESSIONAL' ? 4 : 3;
  return Math.round((completed / total) * 100);
}

export function profileNeedsOnboarding(role: AccountRole | null | undefined, profile: AccountProfile | null | undefined): boolean {
  if (!role || role === 'ADMIN') return false;
  return profileCompletion(profile, role) < 100;
}

export function friendlyAuthError(error: unknown, fallback: string): string {
  if (typeof error === 'object' && error !== null && 'error' in error) {
    const body = error.error;
    if (typeof body === 'object' && body !== null && 'detail' in body) {
      const detail = body.detail;
      if (typeof detail === 'string') return detail;
      if (Array.isArray(detail)) {
        return detail
          .map(item => typeof item === 'object' && item !== null && 'msg' in item ? String(item.msg) : '')
          .filter(Boolean)
          .join(' ');
      }
    }
  }
  return fallback;
}
