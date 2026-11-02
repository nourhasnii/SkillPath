import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { finalize } from 'rxjs';
import { AuthService, AccountRole, AuthUser, friendlyAuthError } from '../auth/auth.service';

@Component({
  selector: 'app-admin-users',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './admin-users.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class AdminUsersComponent implements OnInit {
  private readonly auth = inject(AuthService);

  protected readonly users = signal<AuthUser[]>([]);
  protected readonly search = signal('');
  protected readonly drafts = signal<Record<string, AccountRole>>({});
  protected readonly busyIds = signal<Set<string>>(new Set());
  protected readonly loading = signal(true);
  protected readonly errorMessage = signal('');
  protected readonly successMessage = signal('');
  protected readonly filteredUsers = computed(() => {
    const query = this.search().trim().toLowerCase();
    return this.users().filter(user => !query
      || user.full_name.toLowerCase().includes(query)
      || user.email.toLowerCase().includes(query)
      || user.role.toLowerCase().includes(query));
  });

  ngOnInit(): void {
    this.loadUsers();
  }

  protected loadUsers(): void {
    this.loading.set(true);
    this.errorMessage.set('');
    this.auth.getUsers().pipe(finalize(() => this.loading.set(false))).subscribe({
      next: users => this.users.set(users),
      error: (error: HttpErrorResponse) => this.errorMessage.set(
        friendlyAuthError(error, 'The user directory could not be loaded.')
      )
    });
  }

  protected roleFor(user: AuthUser): AccountRole {
    return this.drafts()[user.id] ?? user.role;
  }

  protected setDraft(user: AuthUser, value: string): void {
    if (value !== 'STUDENT' && value !== 'PROFESSIONAL' && value !== 'ADMIN') return;
    this.drafts.update(current => ({ ...current, [user.id]: value }));
  }

  protected saveRole(user: AuthUser): void {
    const role = this.roleFor(user);
    if (role === user.role || this.busyIds().has(user.id)) return;
    this.errorMessage.set('');
    this.successMessage.set('');
    this.busyIds.update(current => new Set(current).add(user.id));
    this.auth.updateUserRole(user.id, role).pipe(
      finalize(() => this.busyIds.update(current => {
        const next = new Set(current);
        next.delete(user.id);
        return next;
      }))
    ).subscribe({
      next: updated => {
        this.users.update(users => users.map(item => item.id === updated.id ? updated : item));
        this.drafts.update(current => {
          const next = { ...current };
          delete next[user.id];
          return next;
        });
        this.successMessage.set(`Role updated for ${updated.full_name}.`);
      },
      error: (error: HttpErrorResponse) => this.errorMessage.set(
        friendlyAuthError(error, `The role for ${user.full_name} could not be updated.`)
      )
    });
  }
}
