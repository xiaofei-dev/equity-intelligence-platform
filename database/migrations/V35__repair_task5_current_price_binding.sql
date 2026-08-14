-- Align the Task 5 current-portfolio evidence seal with the provider-neutral
-- V22 price contract. Current valuation uses the selected unadjusted close;
-- longitudinal total-return observations remain governed separately by V31.

CREATE OR REPLACE FUNCTION app.task5_validate_position_evidence_v1()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.manifest_id::text,29));
 IF NEW.price_evidence_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM analytics.canonical_evidence_v1 e
   JOIN app.portfolio_context_evidence_manifest_v1 m ON m.id=NEW.manifest_id
   JOIN analytics.evidence_selection_request_v1 q ON q.request_id=NEW.price_selection_request_id
   JOIN analytics.evidence_selector_policy_v1 p ON p.id=q.policy_id
   JOIN analytics.evidence_completed_session_v1 s ON s.id=q.completed_session_id
   JOIN analytics.evidence_selection_result_v1 r ON r.request_id=q.request_id
   JOIN analytics.evidence_selection_seal_v1 z ON z.request_id=q.request_id
   WHERE e.evidence_id=NEW.price_evidence_id AND e.security_id=NEW.security_public_id
     AND r.state='VALID' AND r.selected_evidence_id=e.evidence_id
     AND r.result_content_hash=NEW.price_selection_result_hash
     AND q.security_id=NEW.security_public_id AND q.decision_cutoff=m.decision_cutoff
     AND q.sealed_ingestion_cutoff=m.sealed_ingestion_cutoff
     AND p.domain='DAILY_PRICE' AND p.field_code='CLOSE_PRICE'
     AND p.domain_constraints->>'sessionDate'=to_char(s.session_date,'YYYY-MM-DD')
     AND p.domain_constraints->>'adjustmentMode'='UNADJUSTED'
     AND p.domain_constraints->>'currency'=e.currency
     AND e.domain='DAILY_PRICE' AND e.state='VALID'
     AND e.canonical_data->>'sessionDate'=to_char(s.session_date,'YYYY-MM-DD')
     AND e.canonical_data->>'adjustmentMode'='UNADJUSTED'
     AND e.canonical_data->>'currency'=e.currency AND e.currency='USD'
     AND e.effective_at<=e.available_at AND e.available_at<=e.ingested_at
     AND e.available_at<=m.decision_cutoff AND e.ingested_at<=m.sealed_ingestion_cutoff
     AND (e.stale_after IS NULL OR e.stale_after>=m.decision_cutoff)
     AND e.normalized_record_hash=NEW.price_evidence_hash
     AND e.ingested_at=NEW.price_ingested_at)
 THEN RAISE EXCEPTION 'Task 5 price evidence binding is invalid'; END IF;
 IF NEW.fundamental_assessment_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM analytics.fv_current_assessment_v1 a
   WHERE a.assessment_id=NEW.fundamental_assessment_id AND a.security_id=NEW.security_public_id
     AND a.assessment_content_hash=NEW.fundamental_assessment_hash
     AND a.model_evidence_label=NEW.fundamental_evidence_label)
 THEN RAISE EXCEPTION 'Task 5 Fundamental Value evidence binding is invalid'; END IF;
 IF NEW.quant_decision_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM analytics.quant_research_decision_v1 q
   WHERE q.decision_id=NEW.quant_decision_id AND q.decision_content_hash=NEW.quant_decision_hash
     AND q.model_evidence_label=NEW.quant_evidence_label
     AND EXISTS(SELECT 1 FROM jsonb_array_elements(q.canonical_payload->'signals') s
       WHERE s->>'securityId'=NEW.security_public_id::text))
 THEN RAISE EXCEPTION 'Task 5 Quant evidence binding is invalid'; END IF;
 RETURN NEW;
END $$;

COMMENT ON FUNCTION app.task5_validate_position_evidence_v1() IS
  'V35 Task 5 current valuation binding: exact V22 CLOSE_PRICE and UNADJUSTED evidence; V31 longitudinal total-return semantics are unchanged.';
