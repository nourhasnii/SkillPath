import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';

import { AuthService, AuthUser } from '../auth/auth.service';
import { CareerService } from './career.service';
import { CareerShellComponent } from './career-shell.component';

describe('CareerShellComponent role-aware navigation', () => {
  const renderForRole = async (role: 'STUDENT' | 'PROFESSIONAL' | 'ADMIN') => {
    const user: AuthUser = {
      id: `account-${role.toLowerCase()}`,
      email: `${role.toLowerCase()}@example.test`,
      full_name: `Test ${role}`,
      role,
      profile_iri: `profil_${role.toLowerCase()}`,
      experience: ''
    };

    await TestBed.configureTestingModule({
      imports: [CareerShellComponent],
      providers: [
        provideRouter([]),
        {
          provide: AuthService,
          useValue: {
            currentUser: signal(user),
            logout: vi.fn(() => of(undefined))
          }
        },
        {
          provide: CareerService,
          useValue: {
            context: signal(null),
            loadContext: vi.fn(() => of(null))
          }
        }
      ]
    }).compileComponents();

    const fixture = TestBed.createComponent(CareerShellComponent);
    fixture.detectChanges();
    return fixture;
  };

  it.each(['STUDENT', 'PROFESSIONAL'] as const)(
    'shows both personalized path links for %s users',
    async role => {
      const fixture = await renderForRole(role);
      const links = Array.from(
        fixture.nativeElement.querySelectorAll('nav[aria-label="Career workspace navigation"] a')
      ) as HTMLAnchorElement[];
      const skillGap = links.find(link => link.textContent?.trim() === 'Skill Gap Analysis');
      const personalizedPath = links.find(link => link.textContent?.trim() === 'Personalised Learning Path');
      const optimalPath = links.find(link => link.textContent?.trim() === 'Parcours optimal');
      const careerBridges = links.find(link => link.textContent?.trim() === 'Career bridges');
      const profile = links.find(link => link.textContent?.trim() === 'Profile');
      const catalogue = links.find(link => link.textContent?.trim() === 'Catalogue');
      const evaluations = links.find(link => link.textContent?.trim() === 'My Evaluations');

      expect(skillGap?.getAttribute('href')).toBe('/skill-gap');
      expect(personalizedPath?.getAttribute('href')).toBe('/learning-path');
      expect(optimalPath).toBeDefined();
      expect(optimalPath?.getAttribute('href')).toBe('/parcours-optimal');
      expect(careerBridges?.getAttribute('href')).toBe('/career-bridges');
      const linkPaths = links.map(link => link.getAttribute('href'));
      expect(linkPaths.indexOf('/career-bridges')).toBe(linkPaths.indexOf('/parcours-optimal') + 1);
      expect(evaluations?.getAttribute('href')).toBe('/evaluations');
      expect(profile?.getAttribute('href')).toBe('/account/profile');
      expect(catalogue?.getAttribute('href')).toBe('/catalogue');
      expect(fixture.nativeElement.textContent).not.toContain('Back to workspace');
      expect(fixture.nativeElement.textContent).not.toContain('Career tools');
      expect(fixture.nativeElement.textContent).toContain(role);
      fixture.destroy();
    }
  );

  it('hides the personal pages from the Admin sidebar and keeps the analysis entries', async () => {
    const fixture = await renderForRole('ADMIN');
    const links = Array.from(
      fixture.nativeElement.querySelectorAll('nav[aria-label="Career workspace navigation"] a')
    ) as HTMLAnchorElement[];
    const hrefs = links.map(link => link.getAttribute('href'));

    // Personal pages are removed for Admin.
    expect(hrefs).not.toContain('/skill-gap');
    expect(hrefs).not.toContain('/learning-path');
    expect(hrefs).not.toContain('/parcours-optimal');
    expect(hrefs).not.toContain('/career-bridges');
    expect(hrefs).not.toContain('/evaluations');

    // Every remaining Admin entry is preserved.
    expect(hrefs).toContain('/dashboard');
    expect(hrefs).toContain('/knowledge-graph');
    expect(hrefs).toContain('/dashboard/competences');
    expect(hrefs).toContain('/dashboard/shared-competencies');
    expect(hrefs).toContain('/dashboard/redundant-competencies');
    expect(hrefs).toContain('/dashboard/untaught-competencies');
    expect(hrefs).toContain('/dashboard/generated-paths');
    expect(hrefs).toContain('/semantic-assistant');
    fixture.destroy();
  });

  it('shows repository and administration links in the same shell for Admin', async () => {
    const fixture = await renderForRole('ADMIN');
    const links = Array.from(
      fixture.nativeElement.querySelectorAll('nav[aria-label="Career workspace navigation"] a')
    ) as HTMLAnchorElement[];

    expect(links.some(link => link.getAttribute('href') === '/dashboard/competences')).toBe(true);
    expect(links.some(link => link.getAttribute('href') === '/dashboard/shared-competencies')).toBe(true);
    expect(links.some(link => link.getAttribute('href') === '/parcours-optimal')).toBe(false);
    expect(links.some(link => link.getAttribute('href') === '/catalogue')).toBe(false);
    expect(links.some(link => link.getAttribute('href') === '/account/profile')).toBe(false);
    fixture.destroy();
  });
});
