import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { AuthService, AuthUser } from '../auth/auth.service';
import { DashboardDataService } from '../dashboard/dashboard-data.service';
import { CareerService } from './career.service';
import { CareerSelectorComponent } from './career-selector.component';

describe('CareerSelectorComponent profile authorization', () => {
  it.each(['STUDENT', 'PROFESSIONAL'] as const)(
    'limits %s profile selection to the signed-in user',
    async role => {
      const profileId = `profil_${role.toLowerCase()}`;
      const user: AuthUser = {
        id: `account-${role.toLowerCase()}`,
        email: `${role.toLowerCase()}@example.test`,
        full_name: `Test ${role}`,
        role,
        profile_iri: profileId,
        experience: ''
      };

      await TestBed.configureTestingModule({
        imports: [CareerSelectorComponent],
        providers: [
          {
            provide: AuthService,
            useValue: { currentUser: signal(user) }
          },
          {
            provide: CareerService,
            useValue: {
              loadContext: vi.fn(() => of({
                profileIri: profileId,
                targetOccupation: { id: 'met_target', label: 'Target occupation' },
                acquiredSkills: [],
                followedTrainings: [],
                savedPaths: [],
                profileCompletion: 100
              }))
            }
          },
          {
            provide: DashboardDataService,
            useValue: {
              getList: vi.fn(() => of([{ id: 'met_target', label: 'Target occupation' }]))
            }
          }
        ]
      }).compileComponents();

      const fixture = TestBed.createComponent(CareerSelectorComponent);
      fixture.detectChanges();

      expect(fixture.componentInstance.profiles().map(profile => profile.id)).toEqual([profileId]);
      fixture.destroy();
    }
  );
});
