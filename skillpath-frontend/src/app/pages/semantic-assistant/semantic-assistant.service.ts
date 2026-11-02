import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

/**
 * Typed access to the SkillPath NLP module (`app/nlp.py`).
 *
 * The backend translates a natural-language question into a SPARQL SELECT
 * query using spaCy + rapidfuzz — no LLM API is involved. These shapes mirror
 * exactly what `POST /nlp/query` and `GET /nlp/examples` return.
 */

export type NlpEntityType = 'Competence' | 'Formation' | 'Module' | string;

export interface NlpEntity {
  text: string;
  iri: string;
  type: NlpEntityType | string;
  score: number;
}

export interface NlpQueryResponse {
  question: string;
  intent: string;
  entities: NlpEntity[];
  sparql: string;
  results: Record<string, string>[];
  message: string;
}

export interface NlpExamples {
  examples: string[];
  supported_intents: string[];
}

const API_ROOT = 'http://localhost:8000';

@Injectable({ providedIn: 'root' })
export class SemanticAssistantService {
  private readonly http = inject(HttpClient);

  /**
   * Sends a question to the backend. The signed-in role and profile are read
   * server-side from the authenticated session cookie — never from this body —
   * so the request only carries the question itself.
   */
  ask(question: string): Observable<NlpQueryResponse> {
    return this.http.post<NlpQueryResponse>(
      `${API_ROOT}/nlp/query`,
      { question },
      { withCredentials: true }
    );
  }

  getExamples(): Observable<NlpExamples> {
    return this.http.get<NlpExamples>(`${API_ROOT}/nlp/examples`, {
      withCredentials: true
    });
  }
}
