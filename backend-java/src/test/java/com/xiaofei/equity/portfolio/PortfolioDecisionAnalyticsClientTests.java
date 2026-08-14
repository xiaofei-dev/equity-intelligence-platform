package com.xiaofei.equity.portfolio;

import static org.springframework.test.web.client.ExpectedCount.once;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import tools.jackson.databind.json.JsonMapper;
import java.nio.file.Files;
import java.nio.file.Path;

class PortfolioDecisionAnalyticsClientTests {
	@Test
	void privateProjectionUsesTheServiceAuthenticationHeader() throws Exception {
		RestClient.Builder builder=RestClient.builder().baseUrl("http://analytics.test");
		MockRestServiceServer server=MockRestServiceServer.bindTo(builder).build();
		server.expect(once(),requestTo("http://analytics.test"+PortfolioDecisionAnalyticsClient.INTERNAL_PATH))
				.andExpect(header(PortfolioDecisionAnalyticsClient.SERVICE_AUTH_HEADER,"test-only-service-authorization"))
				.andRespond(withSuccess("{}",MediaType.APPLICATION_JSON));
		var fixture=JsonMapper.builder().build().readTree(Files.readString(Path.of("..","contracts",
				"portfolio-decision-support-v1","spring-private-projection.example.json")));
		var resealed=(tools.jackson.databind.node.ObjectNode)fixture.deepCopy();
		PortfolioDecisionService.sealProjection(resealed);
		org.assertj.core.api.Assertions.assertThat(resealed).isEqualTo(fixture);
		new PortfolioDecisionAnalyticsClient(builder.build()).evaluate(fixture);
		server.verify();
	}
}
