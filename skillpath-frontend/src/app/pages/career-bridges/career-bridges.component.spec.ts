import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Router, provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { CareerBridge, CareerContext, CareerService } from '../../career/career.service';
import { CareerBridgesComponent } from './career-bridges.component';

describe('CareerBridgesComponent', () => {
  const context: CareerContext = {
    profileIri: 'profil_student',
    profileName: 'Student',
    targetOccupation: null,
    acquiredSkills: [],
    followedTrainings: [],
    savedPaths: [],
    profileCompletion: 100,
    level: null,
    requiredLevel: null
  };
  const bridge: CareerBridge = {
    occupationId: 'metier_devops',
    occupation: 'DevOps Engineer',
    family: 'Technology',
    percent: 50,
    coveredNames: ['Linux'],
    missingNames: ['Docker'],
    trainings: [{
      competence: 'Docker',
      trainings: [{
        id: 'formation_docker',
        name: 'Docker foundations',
        durationHours: 4,
        modules: [{ id: 'module_containers', name: 'Containers', durationHours: 2 }]
      }]
    }]
  };

  const setup = async (bridges: CareerBridge[]) => {
    const career = {
      context: signal(context),
      loadContext: vi.fn(() => of(context)),
      getCareerBridges: vi.fn(() => of(bridges)),
      setTargetOccupation: vi.fn(() => of(undefined))
    };
    const router = { navigate: vi.fn(() => Promise.resolve(true)) };

    await TestBed.configureTestingModule({
      imports: [CareerBridgesComponent],
      providers: [
        provideRouter([]),
        { provide: CareerService, useValue: career },
        { provide: Router, useValue: router }
      ]
    }).compileComponents();

    const fixture = TestBed.createComponent(CareerBridgesComponent);
    fixture.detectChanges();
    return { fixture, career, router };
  };

  it('shows bridge details and refreshes the dashboard after setting a target', async () => {
    const { fixture, career, router } = await setup([bridge]);

    expect(fixture.nativeElement.textContent).toContain('Career bridges');
    expect(fixture.nativeElement.textContent).toContain('Other occupations you could reach from your current skills');
    expect(fixture.nativeElement.textContent).toContain('You already cover:');
    expect(fixture.nativeElement.textContent).toContain('Docker foundations');
    expect(fixture.nativeElement.textContent).toContain('Containers');

    const button = fixture.nativeElement.querySelector('button') as HTMLButtonElement;
    button.click();
    fixture.detectChanges();

    expect(career.setTargetOccupation).toHaveBeenCalledWith('profil_student', 'metier_devops');
    expect(career.loadContext).toHaveBeenLastCalledWith(true);
    expect(router.navigate).toHaveBeenCalledWith(['/career']);
    fixture.destroy();
  });

  it('shows an empty state when no bridges are available', async () => {
    const { fixture } = await setup([]);

    expect(fixture.nativeElement.textContent).toContain(
      'No other occupations with required skills are available yet.'
    );
    fixture.destroy();
  });
});
