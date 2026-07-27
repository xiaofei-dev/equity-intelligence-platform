package com.xiaofei.equity.portfolio;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.math.BigDecimal;

import com.xiaofei.equity.portfolio.InvestmentContextContracts.ConstraintValues;
import com.xiaofei.equity.usercontext.UserContextException;

import org.junit.jupiter.api.Test;

class ConstraintPolicyRulesTests {

	private static final ConstraintValues USER_POLICY = new ConstraintValues(
			20,
			new BigDecimal("0.10"),
			new BigDecimal("0.25"),
			new BigDecimal("0.05"),
			BigDecimal.ZERO,
			new BigDecimal("0.05"));

	@Test
	void resolvesEveryFieldToTheStrictestValue() {
		ConstraintValues portfolioPolicy = new ConstraintValues(
				15,
				new BigDecimal("0.08"),
				null,
				new BigDecimal("0.10"),
				BigDecimal.ZERO,
				null);

		ConstraintValues resolved = ConstraintPolicyRules.resolve(
				USER_POLICY, portfolioPolicy);

		assertThat(resolved.maximumPositionCount()).isEqualTo(15);
		assertThat(resolved.maximumPositionWeight()).isEqualByComparingTo("0.08");
		assertThat(resolved.maximumSectorWeight()).isEqualByComparingTo("0.25");
		assertThat(resolved.minimumCashWeight()).isEqualByComparingTo("0.10");
		assertThat(resolved.maximumSpeculativeWeight()).isEqualByComparingTo("0.05");
	}

	@Test
	void acceptsAChildPolicyThatOnlyTightensInheritedLimits() {
		ConstraintValues child = new ConstraintValues(
				10,
				new BigDecimal("0.08"),
				new BigDecimal("0.20"),
				new BigDecimal("0.10"),
				BigDecimal.ZERO,
				new BigDecimal("0.03"));

		ConstraintPolicyRules.requireTightening(USER_POLICY, child);
	}

	@Test
	void rejectsAChildPolicyThatRaisesMaximumPositionWeight() {
		ConstraintValues child = new ConstraintValues(
				null,
				new BigDecimal("0.15"),
				null,
				null,
				null,
				null);

		assertThatThrownBy(() -> ConstraintPolicyRules.requireTightening(USER_POLICY, child))
			.isInstanceOf(UserContextException.class)
			.extracting(exception -> ((UserContextException) exception).code())
			.isEqualTo("CONSTRAINT_RELAXATION_NOT_ALLOWED");
	}

	@Test
	void rejectsAChildPolicyThatLowersMinimumCash() {
		ConstraintValues child = new ConstraintValues(
				null,
				null,
				null,
				new BigDecimal("0.01"),
				null,
				null);

		assertThatThrownBy(() -> ConstraintPolicyRules.requireTightening(USER_POLICY, child))
			.isInstanceOf(UserContextException.class);
	}
}
