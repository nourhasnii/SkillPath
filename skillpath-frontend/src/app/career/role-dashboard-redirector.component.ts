import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { AuthService } from '../auth/auth.service';
import { StudentDashboardComponent } from '../pages/student-dashboard/student-dashboard.component';
import { ProfessionalDashboardComponent } from '../pages/professional-dashboard/professional-dashboard.component';

@Component({
  selector: 'app-role-dashboard-redirector',
  standalone: true,
  imports: [StudentDashboardComponent, ProfessionalDashboardComponent],
  template: `
    @if (role() === 'STUDENT') {
      <app-student-dashboard />
    } @else if (role() === 'PROFESSIONAL') {
      <app-professional-dashboard />
    } @else {
      <div class="sp-state">
        <p>Loading your role-specific dashboard...</p>
      </div>
    }
  `,
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class RoleDashboardRedirectorComponent {
  private readonly auth = inject(AuthService);
  protected readonly role = () => this.auth.currentUser()?.role;
}
