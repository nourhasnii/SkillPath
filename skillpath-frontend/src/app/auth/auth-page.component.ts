import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';
import {
  AuthService,
  AccountRole,
  dashboardForRole,
  destinationAfterLogin,
  friendlyAuthError,
  profileNeedsOnboarding
} from './auth.service';

type AuthPageMode = 'login' | 'register' | 'forgot-password' | 'reset-password';

@Component({
  selector: 'app-auth-page',
  standalone: true,
  imports: [FormsModule, RouterLink],
  templateUrl: './auth-page.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class AuthPageComponent implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly mode = signal<AuthPageMode>('login');
  protected readonly loading = signal(false);
  protected readonly showPassword = signal(false);
  protected readonly showConfirmation = signal(false);
  protected readonly errorMessage = signal('');
  protected readonly successMessage = signal('');
  protected readonly email = signal('');
  protected readonly fullName = signal('');
  protected readonly password = signal('');
  protected readonly passwordConfirmation = signal('');
  protected readonly profileType = signal<'STUDENT' | 'PROFESSIONAL'>('STUDENT');
  protected readonly resetToken = signal('');

  ngOnInit(): void {
    this.route.data.subscribe(data => {
      this.mode.set(data['mode'] as AuthPageMode);
      this.errorMessage.set('');
      this.successMessage.set('');
    });
    this.route.queryParamMap.subscribe(params => {
      const token = params.get('token') ?? '';
      this.resetToken.set(token);
      if (token) {
        window.history.replaceState({}, '', this.router.url.split('?')[0]);
      }
    });
  }

  private redirectAfterAuthentication(userRole: AccountRole, returnUrl: string | null): void {
    if (userRole === 'ADMIN') {
      void this.router.navigateByUrl(dashboardForRole(userRole));
      return;
    }

    this.auth.getProfile().subscribe({
      next: profile => {
        const target = profileNeedsOnboarding(userRole, profile)
          ? `/${userRole.toLowerCase()}/onboarding`
          : destinationAfterLogin(userRole, returnUrl);
        void this.router.navigateByUrl(target);
      },
      error: () => {
        void this.router.navigateByUrl(destinationAfterLogin(userRole, returnUrl));
      }
    });
  }

  protected submit(): void {
    if (this.loading()) return;
    this.errorMessage.set('');
    this.successMessage.set('');
    this.loading.set(true);

    switch (this.mode()) {
      case 'login':
        this.auth.login(this.email(), this.password())
          .pipe(finalize(() => this.loading.set(false)))
          .subscribe({
            next: user => this.redirectAfterAuthentication(user.role, this.route.snapshot.queryParamMap.get('returnUrl')),
            error: (error: HttpErrorResponse) => this.errorMessage.set(
              friendlyAuthError(error, 'Connexion impossible. Vérifiez vos identifiants.')
            )
          });
        return;
      case 'register':
        this.auth.register({
          full_name: this.fullName(),
          email: this.email(),
          password: this.password(),
          password_confirmation: this.passwordConfirmation(),
          profile_type: this.profileType()
        }).pipe(finalize(() => this.loading.set(false))).subscribe({
          next: user => this.redirectAfterAuthentication(user.role, null),
          error: (error: HttpErrorResponse) => this.errorMessage.set(
            friendlyAuthError(error, 'Inscription impossible. Vérifiez les informations saisies.')
          )
        });
        return;
      case 'forgot-password':
        this.auth.forgotPassword(this.email())
          .pipe(finalize(() => this.loading.set(false)))
          .subscribe({
            next: result => this.successMessage.set(result.message),
            error: (error: HttpErrorResponse) => this.errorMessage.set(
              friendlyAuthError(error, 'La demande de réinitialisation ne peut pas être traitée.')
            )
          });
        return;
      case 'reset-password':
        this.auth.resetPassword(this.resetToken(), this.password(), this.passwordConfirmation())
          .pipe(finalize(() => this.loading.set(false)))
          .subscribe({
            next: result => {
              this.successMessage.set(result.message);
              this.password.set('');
              this.passwordConfirmation.set('');
            },
            error: (error: HttpErrorResponse) => this.errorMessage.set(
              friendlyAuthError(error, 'Le lien de réinitialisation est invalide ou expiré.')
            )
          });
    }
  }

  protected setEmail(value: string): void { this.email.set(value); }
  protected setName(value: string): void { this.fullName.set(value); }
  protected setPassword(value: string): void { this.password.set(value); }
  protected setConfirmation(value: string): void { this.passwordConfirmation.set(value); }
  protected setRole(value: 'STUDENT' | 'PROFESSIONAL'): void { this.profileType.set(value); }

  protected passwordMismatch(): boolean {
    return !!this.passwordConfirmation() && this.password() !== this.passwordConfirmation();
  }

  protected title(): string {
    switch (this.mode()) {
      case 'login': return 'Welcome back';
      case 'register': return 'Create your account';
      case 'forgot-password': return 'Reset your password';
      case 'reset-password': return 'Choose a new password';
    }
  }

  protected subtitle(): string {
    switch (this.mode()) {
      case 'login': return 'Sign in to continue your SkillPath journey.';
      case 'register': return 'Build a profile that connects your skills to your next step.';
      case 'forgot-password': return 'We will email a secure, time-limited reset link if the account exists.';
      case 'reset-password': return 'Choose a new password to secure your account.';
    }
  }
}
