import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of, throwError } from 'rxjs';

import { CatalogueTraining, DashboardDataService } from './dashboard/dashboard-data.service';
import { LandingPage } from './landing-page';

const trainings: CatalogueTraining[] = [
  {
    id: 'form_course_a',
    nom: 'Course A',
    type: 'FormationEnLigne',
    duree_heures: 6,
    competences_enseignees: [{ id: 'comp_a', label: 'comp_Python' }],
    prerequis: []
  },
  {
    id: 'form_course_b',
    nom: 'Course B',
    type: 'FormationPresentielle',
    duree_heures: null,
    competences_enseignees: [{ id: 'comp_b', label: 'comp_Communication' }],
    prerequis: []
  },
  {
    id: 'form_course_c',
    nom: 'Course C',
    type: 'Formation',
    duree_heures: 3,
    competences_enseignees: [],
    prerequis: []
  }
];

const setup = async (catalogue = of(trainings)) => {
  await TestBed.configureTestingModule({
    imports: [LandingPage],
    providers: [
      provideRouter([]),
      {
        provide: DashboardDataService,
        useValue: {
          getPublicDashboard: vi.fn(() => of({
            competences: 21,
            formations: 8,
            metiers: 5
          })),
          getPublicCatalogue: vi.fn(() => catalogue),
          getStats: vi.fn(() => of({
            competences: 21, metiers: 5, formations: 8,
            profils: 3, modules: 2, parcours: 1, evaluations: 0
          })),
          getGraph: vi.fn(() => of({ nodes: [], edges: [] })),
          getList: vi.fn(() => of([]))
        }
      }
    ]
  }).compileComponents();
  const fixture = TestBed.createComponent(LandingPage);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
};

describe('LandingPage catalogue preview', () => {
  it('shows live training cards and the three public counters', async () => {
    const fixture = await setup();
    const preview = fixture.nativeElement.querySelector('.catalogue-preview-section') as HTMLElement;
    expect(preview.textContent).toContain('Python');
    expect(preview.textContent).toContain('Communication');
    expect(preview.textContent).toContain('21');
    expect(preview.textContent).toContain('8');
    expect(preview.textContent).toContain('5');
    expect(preview.querySelectorAll('.catalogue-preview-card').length).toBe(3);
    expect(preview.querySelector('a[routerLink="/catalogue"]')).toBeTruthy();
    fixture.destroy();
  });

  it('hides the preview without an error or placeholder when the API fails', async () => {
    const fixture = await setup(throwError(() => new Error('Catalogue unavailable')));
    expect(fixture.nativeElement.querySelector('.catalogue-preview-section')).toBeNull();
    fixture.destroy();
  });
});
