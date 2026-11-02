import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { BehaviorSubject, of } from 'rxjs';
import { DashboardEntityListComponent } from './dashboard-entity-list.component';
import { DashboardDataService } from './dashboard-data.service';

describe('DashboardEntityListComponent route changes', () => {
  it('reloads and updates the list when the entity route parameter changes', async () => {
    const params = new BehaviorSubject(convertToParamMap({ type: 'competences' }));
    const getList = vi.fn(() => of([]));

    await TestBed.configureTestingModule({
      imports: [DashboardEntityListComponent],
      providers: [
        provideRouter([]),
        { provide: ActivatedRoute, useValue: { paramMap: params.asObservable() } },
        { provide: DashboardDataService, useValue: { getList } }
      ]
    }).compileComponents();

    const fixture = TestBed.createComponent(DashboardEntityListComponent);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('h1')?.textContent).toContain('Competences');
    expect(getList).toHaveBeenLastCalledWith('Competence', '', true);

    params.next(convertToParamMap({ type: 'occupations' }));
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('h1')?.textContent).toContain('Occupations');
    expect(getList).toHaveBeenLastCalledWith('Metier', '', true);
  });
});
