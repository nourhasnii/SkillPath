import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { AuthService } from '../auth/auth.service';

@Component({
  selector: 'app-profile-onboarding-success',
  standalone: true,
  imports: [RouterLink],
  templateUrl: './profile-onboarding-success.component.html',
  styleUrl: './profile-onboarding-success.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class ProfileOnboardingSuccessComponent {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly user = this.auth.currentUser;

  protected message(): string {
    return this.user()?.role === 'PROFESSIONAL'
      ? 'Your profile is ready. Let\'s explore your next career move.'
      : 'Your profile is ready. Let\'s analyze your skills.';
  }

  protected primaryLabel(): string {
    return 'Analyze My Skills →';
  }

  protected continue(): void {
    void this.router.navigateByUrl('/skill-gap');
  }
}
