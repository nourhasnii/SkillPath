import { Routes } from '@angular/router';

import { LandingPage } from './landing-page';
import { CareerShellComponent } from './career/career-shell.component';
import { RoleDashboardRedirectorComponent } from './career/role-dashboard-redirector.component';
import { StudentDashboardComponent } from './pages/student-dashboard/student-dashboard.component';
import { ProfessionalDashboardComponent } from './pages/professional-dashboard/professional-dashboard.component';
import { SkillGapComponent } from './pages/skill-gap/skill-gap.component';
import { LearningPathComponent } from './pages/learning-path/learning-path.component';
import { ParcoursOptimalComponent } from './pages/parcours-optimal/parcours-optimal.component';
import { CareerBridgesComponent } from './pages/career-bridges/career-bridges.component';
import { EvaluationsComponent } from './pages/evaluations/evaluations.component';
import { KnowledgeGraphComponent } from './pages/knowledge-graph/knowledge-graph.component';
import { DashboardEntityDetailComponent } from './dashboard/dashboard-entity-detail.component';
import { DashboardEntityFormComponent } from './dashboard/dashboard-entity-form.component';
import { DashboardEntityListComponent } from './dashboard/dashboard-entity-list.component';
import { DashboardHomeComponent } from './dashboard/dashboard-home.component';
import { DashboardLayoutComponent } from './dashboard/dashboard-layout.component';
import { AuthPageComponent } from './auth/auth-page.component';
import { authGuard, profileCompletionGuard, roleGuard } from './auth/auth.guards';
import { AccountProfileComponent } from './dashboard/account-profile.component';
import { AdminUsersComponent } from './dashboard/admin-users.component';
import { RedundantCompetenciesComponent } from './dashboard/redundant-competencies.component';
import { SharedCompetenciesComponent } from './dashboard/shared-competencies.component';
import { UntaughtCompetenciesComponent } from './dashboard/untaught-competencies.component';
import { ProfileOnboardingComponent } from './dashboard/profile-onboarding.component';
import { ProfileOnboardingSuccessComponent } from './dashboard/profile-onboarding-success.component';
import { CatalogueComponent } from './pages/catalogue/catalogue.component';
import { SemanticAssistantComponent } from './pages/semantic-assistant/semantic-assistant.component';

export const routes: Routes = [
	{ path: '', component: LandingPage },
	{ path: 'login', component: AuthPageComponent, data: { mode: 'login' } },
	{ path: 'register', component: AuthPageComponent, data: { mode: 'register' } },
	{ path: 'forgot-password', component: AuthPageComponent, data: { mode: 'forgot-password' } },
	{ path: 'reset-password', component: AuthPageComponent, data: { mode: 'reset-password' } },
	{
		path: '',
		component: CareerShellComponent,
		canActivate: [authGuard, roleGuard],
		data: { roles: ['STUDENT', 'PROFESSIONAL', 'ADMIN'] },
		children: [
			{
				path: 'career',
				component: RoleDashboardRedirectorComponent,
				canActivate: [profileCompletionGuard],
				data: {
					requireProfileCompletion: true,
					title: 'Dashboard',
					subtitle: 'Your readiness, gaps and next steps'
				}
			},
			{
				path: 'skill-gap',
				component: SkillGapComponent,
				canActivate: [roleGuard, profileCompletionGuard],
				data: {
					roles: ['STUDENT', 'PROFESSIONAL'],
					requireProfileCompletion: true,
					title: 'Skill Gap Analysis',
					subtitle: 'Compare your profile with a target occupation'
				}
			},
			{
				path: 'learning-path',
				component: LearningPathComponent,
				canActivate: [roleGuard, profileCompletionGuard],
				data: {
					roles: ['STUDENT', 'PROFESSIONAL'],
					requireProfileCompletion: true,
					title: 'Personalised Learning Path',
					subtitle: 'Your single prerequisite-ordered roadmap'
				}
			},
			{
				path: 'parcours-optimal',
				component: ParcoursOptimalComponent,
				canActivate: [roleGuard, profileCompletionGuard],
				data: {
					roles: ['STUDENT', 'PROFESSIONAL'],
					title: 'Parcours optimal',
					subtitle: 'Compare and customize ranked training paths',
					requireProfileCompletion: true
				}
			},
			{
				path: 'career-bridges',
				component: CareerBridgesComponent,
				canActivate: [roleGuard],
				data: {
					roles: ['STUDENT', 'PROFESSIONAL'],
					title: 'Career bridges',
					subtitle: 'Other occupations you could reach from your current skills'
				}
			},
			{
				path: 'evaluations',
				component: EvaluationsComponent,
				canActivate: [roleGuard],
				data: {
					roles: ['STUDENT', 'PROFESSIONAL'],
					title: 'My Evaluations',
					subtitle: 'Your automatic career assessment and readiness level'
				}
			},
			{
				path: 'catalogue',
				component: CatalogueComponent,
				canActivate: [roleGuard],
				data: {
					roles: ['STUDENT', 'PROFESSIONAL'],
					title: 'Catalogue',
					subtitle: 'Explore real trainings and the skills they teach'
				}
			},
			{
				path: 'catalogue/:id',
				component: CatalogueComponent,
				canActivate: [roleGuard],
				data: {
					roles: ['STUDENT', 'PROFESSIONAL'],
					title: 'Catalogue',
					subtitle: 'Explore real trainings and the skills they teach'
				}
			},
			{
				path: 'knowledge-graph',
				component: KnowledgeGraphComponent,
				canActivate: [profileCompletionGuard],
				data: {
					requireProfileCompletion: true,
					title: 'Knowledge Graph',
					subtitle: 'Explore how everything connects'
				}
			},
			{
				path: 'semantic-assistant',
				component: SemanticAssistantComponent,
				canActivate: [roleGuard],
				data: {
					roles: ['STUDENT', 'PROFESSIONAL', 'ADMIN'],
					title: 'Semantic Assistant',
					subtitle: 'Ask a career question in plain language'
				}
			},
			{
				path: 'account/profile',
				component: AccountProfileComponent,
				canActivate: [roleGuard],
				data: {
					roles: ['STUDENT', 'PROFESSIONAL'],
					title: 'My profile',
					subtitle: 'Manage your career objective, skills, and completed training'
				}
			},
			// Alias of the canonical `/account/profile` route (Smart Profile).
			{ path: 'profile', redirectTo: 'account/profile', pathMatch: 'full' },
			{
				path: 'dashboard',
				component: DashboardLayoutComponent,
				canActivate: [roleGuard],
				data: { roles: ['ADMIN'], title: 'Admin dashboard' },
				children: [
					{ path: '', component: DashboardHomeComponent },
					{ path: 'users', component: AdminUsersComponent },
					{ path: 'redundant-competencies', component: RedundantCompetenciesComponent },
					{ path: 'shared-competencies', component: SharedCompetenciesComponent },
					{ path: 'untaught-competencies', component: UntaughtCompetenciesComponent },
					{ path: 'generated-paths', component: DashboardEntityListComponent },
					{ path: ':type/new', component: DashboardEntityFormComponent },
					{ path: ':type/:id/edit', component: DashboardEntityFormComponent },
					{ path: ':type/:id', component: DashboardEntityDetailComponent },
					{ path: ':type', component: DashboardEntityListComponent }
				]
			},
			{
				path: 'student',
				canActivate: [roleGuard],
				data: { roles: ['STUDENT'] },
				children: [
					{
						path: 'dashboard',
						component: StudentDashboardComponent,
						canActivate: [profileCompletionGuard],
						data: {
							requireProfileCompletion: true,
							title: 'Dashboard',
							subtitle: 'Your readiness, gaps and next steps'
						}
					}
				]
			},
			{
				path: 'professional',
				canActivate: [roleGuard],
				data: { roles: ['PROFESSIONAL'] },
				children: [
					{
						path: 'dashboard',
						component: ProfessionalDashboardComponent,
						canActivate: [profileCompletionGuard],
						data: {
							requireProfileCompletion: true,
							title: 'Dashboard',
							subtitle: 'Your readiness, gaps and next steps'
						}
					}
				]
			}
		]
	},
	{
		path: 'student/onboarding',
		component: ProfileOnboardingComponent,
		canActivate: [authGuard, roleGuard],
		data: { roles: ['STUDENT'] }
	},
	{
		path: 'student/profile-success',
		component: ProfileOnboardingSuccessComponent,
		canActivate: [authGuard, roleGuard, profileCompletionGuard],
		data: { roles: ['STUDENT'], requireProfileCompletion: true }
	},
	{
		path: 'professional/onboarding',
		component: ProfileOnboardingComponent,
		canActivate: [authGuard, roleGuard],
		data: { roles: ['PROFESSIONAL'] }
	},
	{
		path: 'professional/profile-success',
		component: ProfileOnboardingSuccessComponent,
		canActivate: [authGuard, roleGuard, profileCompletionGuard],
		data: { roles: ['PROFESSIONAL'], requireProfileCompletion: true }
	},
];
