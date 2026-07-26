package com.xiaofei.equity.system;

import static org.hamcrest.Matchers.matchesPattern;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.test.web.servlet.MockMvc;

@WebMvcTest(SystemStatusController.class)
class SystemStatusControllerTests {

	@Autowired
	private MockMvc mockMvc;

	@Test
	void returnsServiceStatus() throws Exception {
		mockMvc.perform(get("/api/v1/system/status"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.service").value("backend-java"))
				.andExpect(jsonPath("$.status").value("UP"))
				.andExpect(jsonPath("$.timestamp", matchesPattern("^\\d{4}-\\d{2}-\\d{2}T.*Z$")));
	}
}
