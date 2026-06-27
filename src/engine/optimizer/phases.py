from __future__ import annotations

from collections.abc import Callable

from engine.config.models import (
    CandidateEvaluation,
    DataSnapshot,
    LayerFamily,
    LayerSpec,
    OvernightRunReport,
    PhaseRecord,
    PromotionDecision,
    StrategyGraph,
    ValidationProtocol,
)
from engine.validation.protocol import legacy_validation_protocol


Evaluator = Callable[[StrategyGraph, LayerSpec], CandidateEvaluation]
ValidationExecutor = Callable[[StrategyGraph, list[PhaseRecord]], ValidationProtocol]
HoldoutValidator = ValidationExecutor


class OvernightRunner:
    def __init__(self, snapshot: DataSnapshot, evaluator: Evaluator) -> None:
        self.snapshot = snapshot
        self.evaluator = evaluator

    def run_directional_phase(
        self,
        incumbent: StrategyGraph,
        directional_layers: list[LayerSpec],
    ) -> StrategyGraph:
        best_layer: LayerSpec | None = None
        best_sharpe: float | None = None

        for layer in directional_layers:
            evaluation = self.evaluator(incumbent, layer)
            if evaluation.decision.decision != "accept":
                continue
            if best_sharpe is None or evaluation.oos_result.sharpe > best_sharpe:
                best_layer = layer
                best_sharpe = evaluation.oos_result.sharpe

        if best_layer is None:
            return incumbent
        return incumbent.with_layer(best_layer)

    def run_sequential_phase(
        self,
        incumbent: StrategyGraph,
        candidate_layers: list[LayerSpec],
    ) -> StrategyGraph:
        current = incumbent
        for layer in candidate_layers:
            evaluation = self.evaluator(current, layer)
            if evaluation.decision.decision == "accept":
                current = current.with_layer(layer)
        return current

    def run_pipeline(
        self,
        incumbent: StrategyGraph,
        directional_layers: list[LayerSpec],
        known_good_filters: list[LayerSpec],
        custom_filters: list[LayerSpec],
        exit_layers: list[LayerSpec],
        validation_executor: ValidationExecutor | None = None,
    ) -> OvernightRunReport:
        phase_records: list[PhaseRecord] = []
        backbone_layer = LayerSpec(name=incumbent.backbone, family=LayerFamily.BACKBONE)
        backbone_evaluation = self.evaluator(incumbent, backbone_layer)

        if backbone_evaluation.oos_result.sharpe < 0.05:
            phase_records.append(
                PhaseRecord(
                    phase_name="phase-1",
                    layer_name=incumbent.backbone,
                    decision="abort",
                    accepted=False,
                    oos_sharpe=backbone_evaluation.oos_result.sharpe,
                    selected_parameters=dict(backbone_evaluation.selected_parameters),
                    permutation_count=backbone_evaluation.permutation_count,
                    search_summary=list(backbone_evaluation.search_summary),
                    candidate_trials=list(backbone_evaluation.candidate_trials),
                )
            )
            return OvernightRunReport(
                status="aborted",
                final_strategy=incumbent,
                phase_records=phase_records,
                holdout_decision=None,
                final_evaluation=backbone_evaluation,
            )

        phase_records.append(
            PhaseRecord(
                phase_name="phase-1",
                layer_name=incumbent.backbone,
                decision=backbone_evaluation.decision.decision,
                accepted=False,
                oos_sharpe=backbone_evaluation.oos_result.sharpe,
                selected_parameters=dict(backbone_evaluation.selected_parameters),
                permutation_count=backbone_evaluation.permutation_count,
                search_summary=list(backbone_evaluation.search_summary),
                candidate_trials=list(backbone_evaluation.candidate_trials),
            )
        )

        current = incumbent
        final_evaluation = backbone_evaluation
        current = self._run_directional_phase_with_records(current, directional_layers, phase_records)
        if current.layers:
            final_evaluation = self._evaluate_current_strategy(current)
        current = self._run_sequential_phase_with_records(current, known_good_filters, "phase-3", phase_records)
        if current.layers:
            final_evaluation = self._evaluate_current_strategy(current)
        current = self._run_sequential_phase_with_records(current, custom_filters, "phase-4", phase_records)
        if current.layers:
            final_evaluation = self._evaluate_current_strategy(current)
        current = self._run_sequential_phase_with_records(current, exit_layers, "phase-5", phase_records)
        if current.layers:
            final_evaluation = self._evaluate_current_strategy(current)

        validation_protocol = legacy_validation_protocol(PromotionDecision(decision="accept", reasons=[]))
        holdout_decision = validation_protocol.promotion_decision
        status = "promoted"
        if validation_executor is not None:
            validation_protocol = validation_executor(current, phase_records)
            holdout_decision = validation_protocol.promotion_decision
            if holdout_decision.decision != "accept":
                status = "blocked"

        return OvernightRunReport(
            status=status,
            final_strategy=current,
            phase_records=phase_records,
            holdout_decision=holdout_decision,
            final_evaluation=final_evaluation,
            validation_protocol=validation_protocol,
        )

    def _run_directional_phase_with_records(
        self,
        incumbent: StrategyGraph,
        directional_layers: list[LayerSpec],
        phase_records: list[PhaseRecord],
    ) -> StrategyGraph:
        best_layer: LayerSpec | None = None
        best_sharpe: float | None = None
        evaluations: list[tuple[LayerSpec, CandidateEvaluation]] = []

        for layer in directional_layers:
            evaluation = self.evaluator(incumbent, layer)
            evaluations.append((layer, evaluation))
            if evaluation.decision.decision != "accept":
                continue
            if best_sharpe is None or evaluation.oos_result.sharpe > best_sharpe:
                best_layer = layer
                best_sharpe = evaluation.oos_result.sharpe

        for layer, evaluation in evaluations:
            phase_records.append(
                PhaseRecord(
                    phase_name="phase-2",
                    layer_name=layer.name,
                    decision=evaluation.decision.decision,
                    accepted=best_layer is not None and layer.name == best_layer.name,
                    oos_sharpe=evaluation.oos_result.sharpe,
                    selected_parameters=dict(evaluation.selected_parameters),
                    permutation_count=evaluation.permutation_count,
                    search_summary=list(evaluation.search_summary),
                    candidate_trials=list(evaluation.candidate_trials),
                )
            )

        if best_layer is None:
            return incumbent
        return incumbent.with_layer(best_layer)

    def _run_sequential_phase_with_records(
        self,
        incumbent: StrategyGraph,
        candidate_layers: list[LayerSpec],
        phase_name: str,
        phase_records: list[PhaseRecord],
    ) -> StrategyGraph:
        current = incumbent
        for layer in candidate_layers:
            evaluation = self.evaluator(current, layer)
            accepted = evaluation.decision.decision == "accept"
            phase_records.append(
                PhaseRecord(
                    phase_name=phase_name,
                    layer_name=layer.name,
                    decision=evaluation.decision.decision,
                    accepted=accepted,
                    oos_sharpe=evaluation.oos_result.sharpe,
                    selected_parameters=dict(evaluation.selected_parameters),
                    permutation_count=evaluation.permutation_count,
                    search_summary=list(evaluation.search_summary),
                    candidate_trials=list(evaluation.candidate_trials),
                )
            )
            if accepted:
                current = current.with_layer(layer)
        return current

    def _evaluate_current_strategy(self, strategy: StrategyGraph) -> CandidateEvaluation:
        last_layer = strategy.layers[-1] if strategy.layers else LayerSpec(name=strategy.backbone, family=LayerFamily.BACKBONE)
        return self.evaluator(strategy, last_layer)
