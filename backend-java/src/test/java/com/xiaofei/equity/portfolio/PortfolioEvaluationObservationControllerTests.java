package com.xiaofei.equity.portfolio;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import java.util.List;
import java.util.UUID;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

import com.xiaofei.equity.portfolio.PortfolioDecisionContracts.EvaluationResponse;
import com.xiaofei.equity.portfolio.PortfolioDecisionContracts.ObservationSelectorInput;
import com.xiaofei.equity.portfolio.PortfolioDecisionContracts.RecordObservationRequest;
import com.xiaofei.equity.portfolio.PortfolioDecisionContracts.SealLongitudinalRequest;
import com.xiaofei.equity.portfolio.PortfolioDecisionContracts.CreateThesisReviewRequest;
import com.xiaofei.equity.portfolio.PortfolioDecisionContracts.LongitudinalProjectionResponse;
import com.xiaofei.equity.portfolio.PortfolioDecisionContracts.ThesisReviewState;

class PortfolioEvaluationObservationControllerTests {
	private static final UUID OWNER = UUID.fromString("29000000-0000-4000-8000-000000000001");
	private static final UUID PORTFOLIO = UUID.fromString("29000000-0000-4000-8000-000000000002");
	private static final UUID EVALUATION = UUID.fromString("29000000-0000-4000-8000-000000000003");

	@Test
	void serviceTokenProtectsIdOnlyObservationIngestion() {
		var service = mock(PortfolioDecisionService.class);
		var controller = new PortfolioEvaluationObservationController(service, "test-token");
		var request = request();
		var forbidden = assertThrows(ResponseStatusException.class,
				() -> controller.record("wrong-token", "observation-1", OWNER, PORTFOLIO, EVALUATION, request));
		assertEquals(HttpStatus.FORBIDDEN, forbidden.getStatusCode());

		EvaluationResponse response = mock(EvaluationResponse.class);
		when(service.recordObservation(any(), eq(PORTFOLIO), eq(EVALUATION), eq("observation-1"), eq(request)))
				.thenReturn(response);
		assertEquals(response,
				controller.record("test-token", "observation-1", OWNER, PORTFOLIO, EVALUATION, request));
		verify(service).recordObservation(any(), eq(PORTFOLIO), eq(EVALUATION), eq("observation-1"), eq(request));
	}

	@Test
	void serviceTokenProtectsLongitudinalSealAndHumanThesisReview() {
		var service=mock(PortfolioDecisionService.class);
		var controller=new PortfolioEvaluationObservationController(service,"test-token");
		var maturity=UUID.fromString("29000000-0000-4000-8000-000000000008");
		var seal=new SealLongitudinalRequest(20,maturity);
		var review=new CreateThesisReviewRequest(20,ThesisReviewState.INSUFFICIENT_EVIDENCE,
				"More natural maturity evidence is required.",null);
		assertThrows(ResponseStatusException.class,()->controller.sealLongitudinal("wrong",
				"seal-1",OWNER,PORTFOLIO,EVALUATION,seal));
		assertThrows(ResponseStatusException.class,()->controller.reviewThesis("wrong",
				"review-1",OWNER,PORTFOLIO,EVALUATION,review));
		LongitudinalProjectionResponse response=mock(LongitudinalProjectionResponse.class);
		when(service.sealLongitudinal(any(),eq(PORTFOLIO),eq(EVALUATION),eq("seal-1"),eq(seal)))
				.thenReturn(response);
		when(service.reviewThesis(any(),eq(PORTFOLIO),eq(EVALUATION),eq("review-1"),eq(review)))
				.thenReturn(response);
		assertEquals(response,controller.sealLongitudinal("test-token","seal-1",OWNER,PORTFOLIO,EVALUATION,seal));
		assertEquals(response,controller.reviewThesis("test-token","review-1",OWNER,PORTFOLIO,EVALUATION,review));
	}

	private static RecordObservationRequest request() {
		UUID session = UUID.fromString("29000000-0000-4000-8000-000000000004");
		UUID benchmark = UUID.fromString("29000000-0000-4000-8000-000000000005");
		UUID security = UUID.fromString("29000000-0000-4000-8000-000000000006");
		UUID selection = UUID.fromString("29000000-0000-4000-8000-000000000007");
		var selector = new ObservationSelectorInput(security, selection);
		return new RecordObservationRequest(session,List.of(selector),List.of(selector),benchmark);
	}
}
