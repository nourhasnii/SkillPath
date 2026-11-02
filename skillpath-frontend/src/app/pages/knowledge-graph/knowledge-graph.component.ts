import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  OnInit,
  ViewChild,
  computed,
  inject,
  signal
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute } from '@angular/router';
import type { Edge, Network as NetworkInstance, Node } from 'vis-network/standalone';
import { finalize } from 'rxjs';

import { apiErrorMessage } from '../../dashboard/dashboard-data.service';
import { IconComponent } from '../../career/icon.component';
import {
  CareerGraph,
  CareerGraphNode,
  CareerService,
  humanizeIdentifier
} from '../../career/career.service';

type GraphNodeType = CareerGraphNode['type'];

interface DetailGroup {
  relation: string;
  label: string;
  direction: 'outgoing' | 'incoming';
  items: CareerGraphNode[];
}

interface NodeDetail {
  node: CareerGraphNode;
  typeLabel: string;
  summary: string;
  groups: DetailGroup[];
}

const TYPE_META: Record<GraphNodeType, { label: string; color: string; shape: string; icon: string }> = {
  profile: { label: 'Profile', color: '#5B4FE9', shape: 'hexagon', icon: 'user' },
  skill: { label: 'Skill', color: '#10B981', shape: 'dot', icon: 'sparkle' },
  job: { label: 'Occupation', color: '#2563EB', shape: 'box', icon: 'target' },
  training: { label: 'Training', color: '#F59E0B', shape: 'triangle', icon: 'book' }
};

const TYPE_ORDER: GraphNodeType[] = ['profile', 'skill', 'job', 'training'];

/** Direction-aware wording for each ontology relation present in the graph feed. */
const RELATION_LABELS: Record<string, { outgoing: string; incoming: string }> = {
  aAcquis: { outgoing: 'Skills acquired', incoming: 'Acquired by profile' },
  requiert: { outgoing: 'Skills required', incoming: 'Required by occupation' },
  enseigne: { outgoing: 'Skills taught', incoming: 'Taught by training' },
  aPourPrerequis: { outgoing: 'Prerequisites', incoming: 'Prerequisite for' }
};

/**
 * Interactive view of the ontology.
 *
 * Every node, edge and explanation below is derived from the real `/graph`
 * response — no relation is invented. Node colours, shapes and icons differ per
 * type, connections can be highlighted, and the details panel explains why a
 * skill or a course matters using the actual graph edges.
 */
@Component({
  selector: 'app-knowledge-graph',
  standalone: true,
  imports: [FormsModule, IconComponent],
  templateUrl: './knowledge-graph.component.html',
  styleUrl: './knowledge-graph.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush
})
export class KnowledgeGraphComponent implements OnInit, AfterViewInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly career = inject(CareerService);

  private network?: NetworkInstance;
  private viewReady = false;
  private renderRevision = 0;

  @ViewChild('networkHost') private networkHost!: ElementRef<HTMLDivElement>;

  protected readonly loading = signal(true);
  protected readonly error = signal('');
  protected readonly graph = signal<CareerGraph | null>(null);
  protected readonly visibleTypes = signal<Record<GraphNodeType, boolean>>({
    profile: true,
    skill: true,
    job: true,
    training: true
  });
  protected readonly searchTerm = signal('');
  protected readonly searchFeedback = signal('');
  protected readonly selectedId = signal<string | null>(null);
  protected readonly zoomLevel = signal(100);

  protected readonly typeMeta = TYPE_META;
  protected readonly typeOrder = TYPE_ORDER;

  /** Turns an ontology identifier (`comp_python`) into a readable label. */
  protected displayName(value: string): string {
    return humanizeIdentifier(value);
  }

  protected readonly nodesById = computed(() => {
    const map = new Map<string, CareerGraphNode>();
    for (const node of this.graph()?.nodes ?? []) map.set(node.id, node);
    return map;
  });

  protected readonly visibleNodes = computed(() =>
    (this.graph()?.nodes ?? []).filter(node => this.visibleTypes()[node.type])
  );

  protected readonly visibleEdges = computed(() => {
    const ids = new Set(this.visibleNodes().map(node => node.id));
    return (this.graph()?.edges ?? []).filter(edge => ids.has(edge.from) && ids.has(edge.to));
  });

  protected readonly selected = computed<NodeDetail | null>(() => this.buildDetail(this.selectedId()));

  protected readonly counts = computed(() => {
    const graph = this.graph();
    return { nodes: graph?.nodes.length ?? 0, edges: graph?.edges.length ?? 0 };
  });

  ngOnInit(): void {
    const query = this.route.snapshot.queryParamMap.get('q');
    if (query) this.searchTerm.set(query);

    this.career
      .getGraph()
      .pipe(finalize(() => this.loading.set(false)))
      .subscribe({
        next: graph => {
          this.graph.set(graph);
          if (this.viewReady) this.renderNetwork();
        },
        error: error =>
          this.error.set(
            apiErrorMessage(error, 'The knowledge graph could not be loaded. Check that the backend and Fuseki are running.')
          )
      });

    this.career.loadContext().subscribe({ error: () => undefined });
  }

  ngAfterViewInit(): void {
    this.viewReady = true;
    if (this.graph()) this.renderNetwork();
  }

  ngOnDestroy(): void {
    this.viewReady = false;
    this.renderRevision += 1;
    this.network?.destroy();
  }

  protected toggleType(type: GraphNodeType): void {
    this.visibleTypes.update(visible => ({ ...visible, [type]: !visible[type] }));
    const selected = this.selectedId();
    if (selected && !this.visibleNodes().some(node => node.id === selected)) {
      this.selectedId.set(null);
    }
    this.renderNetwork();
  }

  protected onSearchInput(value: string): void {
    this.searchTerm.set(value);
  }

  protected runSearch(): void {
    const term = this.searchTerm().trim().toLowerCase();
    if (!term) {
      this.searchFeedback.set('');
      this.clearSelection();
      return;
    }
    const matches = this.visibleNodes().filter(node =>
      humanizeIdentifier(node.label).toLowerCase().includes(term)
    );
    if (!matches.length) {
      this.searchFeedback.set(`No entity matches “${this.searchTerm().trim()}”.`);
      this.clearSelection();
      return;
    }
    this.searchFeedback.set(
      `${matches.length} ${matches.length === 1 ? 'entity matches' : 'entities match'} “${this.searchTerm().trim()}”.`
    );
    this.network?.setSelection({ nodes: matches.map(node => node.id) });
    if (matches.length === 1) {
      this.selectNode(matches[0].id);
    } else {
      this.network?.fit({ nodes: matches.map(node => node.id), animation: true });
    }
  }

  protected selectNode(id: string): void {
    this.selectedId.set(id);
    this.highlight(id);
  }

  protected clearSelection(): void {
    this.selectedId.set(null);
    this.network?.unselectAll();
  }

  protected zoom(direction: 1 | -1): void {
    if (!this.network) return;
    this.network.moveTo({ scale: this.network.getScale() * (direction === 1 ? 1.25 : 0.8) });
    this.syncZoom();
  }

  protected zoomToFit(): void {
    this.network?.fit({ animation: true });
    this.syncZoom();
  }

  protected resetView(): void {
    this.clearSelection();
    this.searchTerm.set('');
    this.searchFeedback.set('');
    this.visibleTypes.set({ profile: true, skill: true, job: true, training: true });
    this.renderNetwork();
  }

  protected focusNode(id: string): void {
    this.selectNode(id);
    this.network?.focus(id, { scale: 1.25, animation: { duration: 400, easingFunction: 'easeInOutQuad' } });
  }

  protected isAcquired(node: CareerGraphNode): boolean {
    return (this.career.context()?.acquiredSkills ?? []).includes(node.id);
  }

  private highlight(id: string): void {
    const edges = this.graph()?.edges ?? [];
    const nodeIds = new Set<string>([id]);
    const edgeIds: string[] = [];
    for (const edge of edges) {
      if (edge.from === id || edge.to === id) {
        nodeIds.add(edge.from);
        nodeIds.add(edge.to);
        edgeIds.push(edge.id);
      }
    }
    this.network?.setSelection({ nodes: [...nodeIds], edges: edgeIds });
  }

  private buildDetail(id: string | null): NodeDetail | null {
    if (!id) return null;
    const node = this.nodesById().get(id);
    if (!node) return null;

    const edges = this.graph()?.edges ?? [];
    const groups = new Map<string, DetailGroup>();

    for (const edge of edges) {
      const isSource = edge.from === id;
      const isTarget = edge.to === id;
      if (!isSource && !isTarget) continue;
      const otherId = isSource ? edge.to : edge.from;
      const other = this.nodesById().get(otherId);
      if (!other) continue;

      const direction: 'outgoing' | 'incoming' = isSource ? 'outgoing' : 'incoming';
      const key = `${edge.relation}:${direction}`;
      const label = RELATION_LABELS[edge.relation]?.[direction] ?? edge.relation;
      const group = groups.get(key) ?? { relation: edge.relation, label, direction, items: [] };
      if (!group.items.some(item => item.id === other.id)) group.items.push(other);
      groups.set(key, group);
    }

    const ordered = [...groups.values()].sort(
      (a, b) => TYPE_ORDER.indexOf(a.items[0]?.type) - TYPE_ORDER.indexOf(b.items[0]?.type)
    );

    return {
      node,
      typeLabel: TYPE_META[node.type].label,
      summary: this.summarize(node, ordered),
      groups: ordered
    };
  }

  /** One sentence per node, built only from the relations actually returned. */
  private summarize(node: CareerGraphNode, groups: DetailGroup[]): string {
    const find = (relation: string, direction: 'outgoing' | 'incoming') =>
      groups.find(group => group.relation === relation && group.direction === direction)?.items ?? [];

    if (node.type === 'skill') {
      const required = find('requiert', 'incoming');
      const taught = find('enseigne', 'incoming');
      const parts: string[] = [];
      parts.push(
        required.length
          ? `Required by ${required.length} occupation${required.length === 1 ? '' : 's'}.`
          : 'No occupation lists this skill as required.'
      );
      parts.push(
        taught.length
          ? `${taught.length} training${taught.length === 1 ? '' : 's'} in the catalogue teach it.`
          : 'No training in the catalogue teaches it yet, so this gap cannot be closed through the current catalogue.'
      );
      if (!this.isAcquired(node) && this.career.context()?.profileIri) {
        parts.push('You have not added this skill to your profile.');
      }
      return parts.join(' ');
    }

    if (node.type === 'job') {
      const required = find('requiert', 'outgoing');
      return required.length
        ? `This occupation requires ${required.length} skill${required.length === 1 ? '' : 's'}.`
        : 'No required skill is listed for this occupation yet.';
    }

    if (node.type === 'training') {
      const taught = find('enseigne', 'outgoing');
      const prereqs = find('aPourPrerequis', 'outgoing');
      const unlocks = find('aPourPrerequis', 'incoming');
      const parts = [
        taught.length
          ? `Teaches ${taught.length} skill${taught.length === 1 ? '' : 's'}.`
          : 'This training is not linked to any skill yet.'
      ];
      parts.push(
        prereqs.length ? `Requires ${prereqs.length} prerequisite training${prereqs.length === 1 ? '' : 's'}.` : ''
      );
      parts.push(
        unlocks.length ? `It unlocks ${unlocks.length} further training${unlocks.length === 1 ? '' : 's'}.` : ''
      );
      return parts.filter(Boolean).join(' ');
    }

    const acquired = find('aAcquis', 'outgoing');
    return acquired.length
      ? `This profile has declared ${acquired.length} skill${acquired.length === 1 ? '' : 's'} as acquired.`
      : 'This profile has not declared any skill as acquired yet.';
  }

  private syncZoom(): void {
    if (!this.network) return;
    this.zoomLevel.set(Math.round(this.network.getScale() * 100));
  }

  private async renderNetwork(): Promise<void> {
    const data = this.graph();
    if (!data) return;

    const revision = ++this.renderRevision;
    this.network?.destroy();
    this.network = undefined;

    const { Network } = await import('vis-network/standalone');
    if (!this.viewReady || revision !== this.renderRevision) return;

    const filtered = this.visibleNodes();
    const visibleIds = new Set(filtered.map(node => node.id));
    const showEdges = this.visibleEdges().filter(edge => visibleIds.has(edge.from) && visibleIds.has(edge.to));

    const nodes: Node[] = filtered.map(node => {
      const meta = TYPE_META[node.type];
      return {
        id: node.id,
        label: this.wrap(humanizeIdentifier(node.label)),
        title: `${humanizeIdentifier(node.label)} · ${meta.label}`,
        group: node.type,
        shape: meta.shape,
        size: node.type === 'profile' ? 26 : 20,
        color: {
          background: meta.color,
          border: '#FFFFFF',
          highlight: { background: meta.color, border: '#0F172A' },
          hover: { background: meta.color, border: '#5B4FE9' }
        },
        font: { face: 'Inter', color: '#0F172A', size: 13, vadjust: 2 }
      };
    });

    const edges: Edge[] = showEdges.map(edge => ({
      id: edge.id,
      from: edge.from,
      to: edge.to,
      title: RELATION_LABELS[edge.relation]
        ? `${RELATION_LABELS[edge.relation].outgoing}`
        : edge.relation,
      arrows: { to: { enabled: true, scaleFactor: 0.55 } },
      color: { color: '#CBD3E4', highlight: '#5B4FE9', hover: '#8C84F0' },
      width: 1.4
    }));

    this.network = new Network(
      this.networkHost.nativeElement,
      { nodes, edges },
      {
        autoResize: true,
        interaction: { hover: true, keyboard: true, tooltipDelay: 160, multiselect: false },
        physics: { stabilization: { iterations: 180 }, solver: 'forceAtlas2Based' },
        nodes: {
          borderWidth: 2,
          shadow: { enabled: true, color: 'rgba(15, 23, 42, .12)', size: 10, x: 0, y: 4 },
          chosen: true
        },
        edges: {
          smooth: { enabled: true, type: 'dynamic', roundness: 0.5 },
          chosen: true
        }
      }
    );

    this.network.on('click', params => {
      const id = params.nodes?.[0];
      if (typeof id === 'string') {
        this.selectedId.set(id);
        this.highlight(id);
      } else {
        this.selectedId.set(null);
      }
    });

    this.network.on('zoom', () => this.syncZoom());
    this.syncZoom();

    const selected = this.selectedId();
    if (selected && visibleIds.has(selected)) {
      this.highlight(selected);
      return;
    }

    // Start on the user's target occupation when the graph is large enough to need it.
    const target = this.career.context()?.targetOccupation?.id ?? null;
    if (target && visibleIds.has(target) && filtered.length > 12) {
      this.selectedId.set(target);
      this.highlight(target);
      this.network.focus(target, { scale: 1.1, animation: false });
      return;
    }

    this.network.fit({ animation: false });
  }

  /** vis-network does not wrap long labels, so short names stay readable on one line. */
  private wrap(label: string): string {
    return label.length > 22 ? `${label.slice(0, 21)}…` : label;
  }
}
