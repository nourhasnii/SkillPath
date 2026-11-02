import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { BehaviorSubject, of } from 'rxjs';

import { AuthService } from '../../auth/auth.service';
import { DashboardDataService } from '../../dashboard/dashboard-data.service';
import { CatalogueComponent } from './catalogue.component';

describe('CatalogueComponent', () => {
  const training = {
    id: 'form_python',
    nom: 'Python fundamentals',
    type: 'FormationEnLigne',
    duree_heures: 6,
    competences_enseignees: [{ id: 'comp_python', label: 'comp_Python' }],
    prerequis: [{ id: 'form_intro', label: 'form_Introduction' }],
    modules: [{ id: 'mod_basics', label: 'mod_Basics' }]
  };
  const module = {
    id: 'mod_basics',
    nom: 'mod_Basics',
    competences_enseignees: [{ id: 'comp_loops', label: 'comp_Loops' }]
  };

  const setup = async () => {
    const params = new BehaviorSubject(convertToParamMap({ id: 'form_python' }));
    const followProfileTrainings = vi.fn(() => of({
      profil: 'profil_student',
      formations_suivies: ['form_python']
    }));
    const data = {
      getPublicCatalogue: vi.fn(() => of([training])),
      getPublicTraining: vi.fn(() => of(training)),
      getPublicModule: vi.fn(() => of(module)),
      followProfileTrainings
    };
    const profile = {
      id: 'account-student',
      email: 'student@example.test',
      full_name: 'Student',
      role: 'STUDENT' as const,
      profile_iri: 'profil_student',
      experience: '',
      profile: {
        id: 'profil_student',
        type: 'ProfilUtilisateur',
        class: 'ProfilEtudiant',
        label: 'Student',
        properties: {},
        relations: { aSuivi: [] }
      }
    };

    await TestBed.configureTestingModule({
      imports: [CatalogueComponent],
      providers: [
        provideRouter([]),
        { provide: ActivatedRoute, useValue: { paramMap: params.asObservable() } },
        { provide: DashboardDataService, useValue: data },
        {
          provide: AuthService,
          useValue: {
            currentUser: signal(profile),
            getProfile: vi.fn(() => of(profile))
          }
        }
      ]
    }).compileComponents();
    const fixture = TestBed.createComponent(CatalogueComponent);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    return { fixture, params, data, followProfileTrainings };
  };

  it('loads real training and module details with humanized labels', async () => {
    const { fixture, data } = await setup();
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Python fundamentals');
    expect(text).toContain('Python');
    expect(text).toContain('Introduction');
    expect(text).toContain('Basics');
    expect(text).toContain('Loops');
    expect(data.getPublicTraining).toHaveBeenCalledWith('form_python');
    expect(data.getPublicModule).toHaveBeenCalledWith('mod_basics');
    fixture.destroy();
  });

  it('adds a followed training without changing the existing profile list', async () => {
    const { fixture, followProfileTrainings } = await setup();
    const button = fixture.nativeElement.querySelector('.follow-button') as HTMLButtonElement;
    button.click();
    fixture.detectChanges();

    expect(followProfileTrainings).toHaveBeenCalledWith('profil_student', ['form_python']);
    expect(fixture.nativeElement.textContent).toContain('Followed');
    expect(fixture.nativeElement.textContent).toContain('Training marked as followed.');
    fixture.destroy();
  });

  it('reloads details when the route identifier changes', async () => {
    const { fixture, params, data } = await setup();
    params.next(convertToParamMap({ id: 'form_next' }));
    fixture.detectChanges();
    await fixture.whenStable();

    expect(data.getPublicTraining).toHaveBeenCalledWith('form_next');
    fixture.destroy();
  });
});
