"""Generate ranked, prerequisite-valid training paths from catalogue facts."""

from collections.abc import Iterable, Mapping, Set
from math import inf

MAX_CANDIDATE_PATHS = 10


def generate_learning_path_candidates(
    required_competencies: Iterable[str],
    acquired_competencies: Iterable[str],
    training_competencies: Mapping[str, Set[str]],
    prerequisites: Mapping[str, Set[str]],
    training_durations: Mapping[str, int | None],
    catalogue_trainings: Iterable[str],
    followed_trainings: Iterable[str],
    max_duration_hours: int | None = None,
    candidate_limit: int = MAX_CANDIDATE_PATHS,
) -> dict:
    """Return real catalogue combinations ranked by coverage, duration, and size.

    Candidate combinations are explored by branching on the least-supported
    uncovered skill. Each selected training adds its complete prerequisite
    closure; cyclic or unavailable prerequisite chains are rejected. When a
    duration constraint is supplied, paths with unknown durations are excluded
    because the constraint cannot otherwise be verified.
    """
    required = set(required_competencies)
    acquired = required & set(acquired_competencies)
    missing = required - acquired
    catalogue = set(catalogue_trainings)
    followed = set(followed_trainings)
    skill_courses: dict[str, set[str]] = {skill: set() for skill in missing}
    catalogue_skill_courses: dict[str, set[str]] = {skill: set() for skill in missing}

    for training, skills in training_competencies.items():
        if training not in catalogue:
            continue
        for skill in skills & missing:
            catalogue_skill_courses[skill].add(training)
            if training not in followed:
                skill_courses[skill].add(training)

    closures: dict[str, frozenset[str]] = {}
    invalid_closures: set[str] = set()

    def prerequisite_closure(
        training: str, visiting: frozenset[str] = frozenset()
    ) -> frozenset[str] | None:
        if training in followed:
            return frozenset()
        if training not in catalogue or training in visiting:
            return None
        if training in closures:
            return closures[training]
        included = {training}
        next_visiting = visiting | {training}
        for prerequisite in prerequisites.get(training, set()):
            if prerequisite in followed:
                continue
            prerequisite_path = prerequisite_closure(prerequisite, next_visiting)
            if prerequisite_path is None:
                return None
            included.update(prerequisite_path)
        result = frozenset(included)
        closures[training] = result
        return result

    for training in catalogue:
        if prerequisite_closure(training) is None:
            invalid_closures.add(training)

    covered_by: dict[str, frozenset[str]] = {
        training: frozenset(
            skill
            for included_training in closure
            for skill in training_competencies.get(included_training, set())
        ) & missing
        for training, closure in closures.items()
    }

    candidates_by_trainings: dict[frozenset[str], dict] = {}
    visited: set[tuple[frozenset[str], frozenset[str]]] = set()

    def current_duration(selected: frozenset[str]) -> int | None:
        values = [training_durations.get(training) for training in selected]
        if any(value is None for value in values):
            return None
        return sum(value for value in values if value is not None)

    def visit(selected: frozenset[str], skipped: frozenset[str]) -> None:
        state = (selected, skipped)
        if state in visited:
            return
        visited.add(state)
        covered = frozenset(
            skill
            for training in selected
            for skill in training_competencies.get(training, set())
        ) & missing
        unresolved = missing - covered - skipped
        if not unresolved:
            ordered = _topological_order(selected, prerequisites, followed)
            if ordered is None:
                return
            duration = current_duration(selected)
            if max_duration_hours is not None and (
                duration is None or duration > max_duration_hours
            ):
                return
            candidates_by_trainings[selected] = {
                "training_ids": ordered,
                "covered_competencies": tuple(sorted(covered)),
                "uncovered_competencies": tuple(sorted(missing - covered)),
                "duration_hours": duration,
                "duration_available": duration is not None,
                "prerequisites_valid": True,
            }
            return

        options_by_skill: dict[str, list[str]] = {}
        for skill in unresolved:
            options = []
            for training in skill_courses[skill]:
                closure = closures.get(training)
                if closure is None or closure <= selected:
                    continue
                updated = selected | closure
                duration = current_duration(updated)
                if max_duration_hours is not None and (
                    duration is None or duration > max_duration_hours
                ):
                    continue
                options.append(training)
            options_by_skill[skill] = sorted(options)

        skill = min(unresolved, key=lambda item: (len(options_by_skill[item]), item))
        options = options_by_skill[skill]
        for training in options:
            visit(selected | closures[training], skipped)
        if not options or max_duration_hours is not None:
            visit(selected, skipped | {skill})

    visit(frozenset(), frozenset())

    all_candidates = list(candidates_by_trainings.values())

    def dominates(candidate: dict, other: dict) -> bool:
        candidate_coverage = set(candidate["covered_competencies"])
        other_coverage = set(other["covered_competencies"])
        if not other_coverage <= candidate_coverage:
            return False
        if len(candidate["training_ids"]) > len(other["training_ids"]):
            return False
        candidate_duration = candidate["duration_hours"]
        other_duration = other["duration_hours"]
        if candidate_duration is None and other_duration is not None:
            return False
        if (
            candidate_duration is not None
            and other_duration is not None
            and candidate_duration > other_duration
        ):
            return False
        return (
            candidate_coverage != other_coverage
            or len(candidate["training_ids"]) < len(other["training_ids"])
            or (candidate_duration is not None and other_duration is None)
            or (
                candidate_duration is not None
                and other_duration is not None
                and candidate_duration < other_duration
            )
        )

    non_dominated = [
        candidate
        for candidate in all_candidates
        if not any(
            dominates(other, candidate)
            for other in all_candidates
            if other is not candidate
        )
    ]
    ranked = sorted(
        non_dominated,
        key=lambda candidate: (
            -len(candidate["covered_competencies"]),
            candidate["duration_hours"] is None,
            candidate["duration_hours"] if candidate["duration_hours"] is not None else inf,
            len(candidate["training_ids"]),
            candidate["training_ids"],
        ),
    )
    ranked = ranked[:max(1, candidate_limit)]
    for rank, candidate in enumerate(ranked, start=1):
        covered_count = len(candidate["covered_competencies"])
        ratio = covered_count / len(missing) if missing else 1.0
        duration_text = (
            f'{candidate["duration_hours"]} h'
            if candidate["duration_available"]
            else "duration unavailable"
        )
        candidate["rank"] = rank
        candidate["coverage_ratio"] = round(ratio, 4)
        candidate["ranking_explanation"] = (
            f"Covers {covered_count}/{len(missing)} missing competencies "
            f"({ratio:.0%}); {len(candidate['training_ids'])} training(s); "
            f"{duration_text}; all prerequisites are satisfied."
        )

    unavailable_competencies = sorted(
        skill for skill in missing if not catalogue_skill_courses[skill]
    )
    prerequisite_blocked = sorted(
        skill
        for skill in missing
        if skill_courses[skill]
        and not any(training in closures for training in skill_courses[skill])
    )
    return {
        "required_competencies": sorted(required),
        "acquired_competencies": sorted(acquired),
        "missing_competencies": sorted(missing),
        "catalogue_unavailable_competencies": unavailable_competencies,
        "prerequisite_blocked_competencies": prerequisite_blocked,
        "invalid_trainings": sorted(invalid_closures),
        "candidates": ranked,
    }


def _topological_order(
    selected: Iterable[str],
    prerequisites: Mapping[str, Set[str]],
    followed: set[str],
) -> tuple[str, ...] | None:
    remaining = set(selected)
    selected_trainings = set(remaining)
    completed = set(followed)
    ordered: list[str] = []
    depths: dict[str, int] = {}

    def depth(training: str, visiting: set[str]) -> int | None:
        if training in depths:
            return depths[training]
        if training in visiting:
            return None
        visiting.add(training)
        dependencies = prerequisites.get(training, set()) & selected_trainings
        dependency_depths = [depth(dependency, visiting) for dependency in dependencies]
        visiting.remove(training)
        if any(value is None for value in dependency_depths):
            return None
        result = max(
            (value + 1 for value in dependency_depths if value is not None),
            default=0,
        )
        depths[training] = result
        return result

    if any(depth(training, set()) is None for training in selected_trainings):
        return None

    while remaining:
        ready = sorted(
            training
            for training in remaining
            if prerequisites.get(training, set()) <= completed
        )
        if not ready:
            return None
        training = min(ready, key=lambda item: (depths[item], item))
        remaining.remove(training)
        completed.add(training)
        ordered.append(training)
    return tuple(ordered)
