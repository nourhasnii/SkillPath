import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { finalize } from 'rxjs';

import { IconComponent } from '../../career/icon.component';
import { apiErrorMessage } from '../../dashboard/dashboard-data.service';
import { NlpQueryResponse, SemanticAssistantService } from './semantic-assistant.service';

/** Local name of an ontology IRI (`http://…#comp_Python` → `comp_Python`). */
export function localIriName(iri: string): string {
  if (!iri) return '';
  const hash = iri.lastIndexOf('#');
  return hash >= 0 ? iri.slice(hash + 1) : iri;
}

/**
 * Semantic Assistant — turns a natural-language question into an executable
 * SPARQL SELECT query (spaCy + rapidfuzz, no LLM) and shows the intent, the
 * resolved entities, the generated query and the result table.
 */
@Component({
  selector: 'app-semantic-assistant',
  standalone: true,
  imports: [FormsModule, IconComponent],
  templateUrl: './semantic-assistant.component.html',
  styleUrl: './semantic-assistant.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class SemanticAssistantComponent implements OnInit {
  private readonly nlp = inject(SemanticAssistantService);
  private readonly destroyRef = inject(DestroyRef);
  private copyTimeout?: number;

  protected readonly question = signal('');
  protected readonly examples = signal<string[]>([]);
  protected readonly response = signal<NlpQueryResponse | null>(null);
  protected readonly loading = signal(false);
  protected readonly error = signal('');
  protected readonly copied = signal(false);

  protected readonly columns = computed(() => {
    const columns: string[] = [];
    for (const row of this.response()?.results ?? []) {
      for (const key of Object.keys(row)) {
        if (!columns.includes(key)) columns.push(key);
      }
    }
    return columns;
  });

  protected readonly hasResults = computed(() => (this.response()?.results.length ?? 0) > 0);
  protected readonly localName = localIriName;

  ngOnInit(): void {
    this.destroyRef.onDestroy(() => {
      if (this.copyTimeout !== undefined) window.clearTimeout(this.copyTimeout);
    });

    this.nlp.getExamples().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      next: payload => this.examples.set(payload.examples ?? []),
      error: () => undefined
    });
  }

  protected updateQuestion(value: string): void {
    this.question.set(value);
  }

  protected useExample(example: string): void {
    this.question.set(example);
    this.submit();
  }

  protected submit(): void {
    const question = this.question().trim();
    if (!question || this.loading()) return;

    this.loading.set(true);
    this.error.set('');
    this.response.set(null);
    this.copied.set(false);

    this.nlp.ask(question).pipe(
      takeUntilDestroyed(this.destroyRef),
      finalize(() => this.loading.set(false))
    ).subscribe({
      next: response => this.response.set(response),
      error: (error: HttpErrorResponse) => this.error.set(
        apiErrorMessage(error, 'The assistant could not reach the knowledge service.')
      )
    });
  }

  protected copySparql(): void {
    const sparql = this.response()?.sparql;
    if (!sparql) return;
    navigator.clipboard?.writeText(sparql).then(() => {
      this.copied.set(true);
      if (this.copyTimeout !== undefined) window.clearTimeout(this.copyTimeout);
      this.copyTimeout = window.setTimeout(() => this.copied.set(false), 2000);
    }).catch(() => undefined);
  }

  protected cellValue(row: Record<string, string>, column: string): string {
    const value = row[column];
    return value === undefined || value === '' ? '—' : value;
  }
}
