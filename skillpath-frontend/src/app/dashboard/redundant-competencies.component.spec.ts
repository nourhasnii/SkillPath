import { TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { HttpErrorResponse } from '@angular/common/http';
import { RedundantCompetenciesComponent } from './redundant-competencies.component';
import { DashboardDataService, RedundantCompetenciesReport } from './dashboard-data.service';

function reportFixture(): RedundantCompetenciesReport {
  return {
    threshold: 0.75,
    total_competencies: 3,
    pair_count: 2,
    pairs: [
      {
        id_a: 'comp_Python',
        name_a: 'comp_Python',
        class_a: 'CompetenceTechnique',
        id_b: 'comp_PythonProg',
        name_b: 'Python',
        class_b: 'CompetenceTechnique',
        score: 1,
        explanation: 'Noms normalisés identiques : doublon très probable.'
      },
      {
        id_a: 'comp_GestionProjet',
        name_a: 'comp_GestionProjet',
        class_a: 'CompetenceTransverse',
        id_b: 'comp_GestionProjets',
        name_b: 'Gestion des projets',
        class_b: 'CompetenceTransverse',
        score: 0.82,
        explanation: 'Tokens communs : gestion, projet.'
      }
    ]
  };
}

async function setup(getRedundantCompetencies = vi.fn(() => of(reportFixture()))) {
  await TestBed.configureTestingModule({
    imports: [RedundantCompetenciesComponent],
    providers: [{ provide: DashboardDataService, useValue: { getRedundantCompetencies } }]
  }).compileComponents();

  const fixture = TestBed.createComponent(RedundantCompetenciesComponent);
  fixture.detectChanges();
  return { fixture, getRedundantCompetencies };
}

describe('RedundantCompetenciesComponent', () => {
  it('scans on init and renders each candidate pair with score and explanation', async () => {
    const { fixture, getRedundantCompetencies } = await setup();

    expect(getRedundantCompetencies).toHaveBeenCalledWith(0.75);
    const rows = fixture.nativeElement.querySelectorAll('tbody tr');
    expect(rows.length).toBe(2);
    expect(fixture.nativeElement.textContent).toContain('comp_PythonProg');
    expect(fixture.nativeElement.textContent).toContain('100 %');
    expect(fixture.nativeElement.textContent).toContain('82 %');
    expect(rows[0].textContent).toContain('doublon');
  });

  it('filters pairs by search term across both competencies', async () => {
    const { fixture } = await setup();

    const input = fixture.nativeElement.querySelector('input') as HTMLInputElement;
    input.value = 'gestion';
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();

    const rows = fixture.nativeElement.querySelectorAll('tbody tr');
    expect(rows.length).toBe(1);
    expect(rows[0].textContent).toContain('comp_GestionProjet');
  });

  it('rescans with the newly selected threshold', async () => {
    const getRedundantCompetencies = vi.fn(() => of(reportFixture()));
    const { fixture } = await setup(getRedundantCompetencies);

    const selects = fixture.nativeElement.querySelectorAll('select') as NodeListOf<HTMLSelectElement>;
    const thresholdSelect = selects[1];
    thresholdSelect.value = thresholdSelect.options[1].value;
    thresholdSelect.dispatchEvent(new Event('change'));
    fixture.detectChanges();

    expect(getRedundantCompetencies).toHaveBeenLastCalledWith(0.7);
  });

  it('shows an error state when the scan fails', async () => {
    const getRedundantCompetencies = vi.fn(() =>
      throwError(() => new HttpErrorResponse({ status: 502, error: { detail: 'Fuseki indisponible.' } }))
    );
    const { fixture } = await setup(getRedundantCompetencies);

    const alert = fixture.nativeElement.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('Fuseki indisponible.');
    expect(fixture.nativeElement.querySelectorAll('tbody tr').length).toBe(0);
  });
});
