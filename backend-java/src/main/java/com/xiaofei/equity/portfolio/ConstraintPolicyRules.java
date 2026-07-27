package com.xiaofei.equity.portfolio;

import static com.xiaofei.equity.portfolio.InvestmentContextContracts.ConstraintValues;

import com.xiaofei.equity.usercontext.UserContextException;

public final class ConstraintPolicyRules {

	private ConstraintPolicyRules() {
	}

	public static void requireTightening(ConstraintValues parent, ConstraintValues child) {
		if (parent == null) {
			return;
		}
		requireMaximum(parent.maximumPositionCount(), child.maximumPositionCount());
		requireMaximum(parent.maximumPositionWeight(), child.maximumPositionWeight());
		requireMaximum(parent.maximumSectorWeight(), child.maximumSectorWeight());
		requireMinimum(parent.minimumCashWeight(), child.minimumCashWeight());
		requireMaximum(parent.maximumLeverageRatio(), child.maximumLeverageRatio());
		requireMaximum(parent.maximumSpeculativeWeight(), child.maximumSpeculativeWeight());
	}

	public static ConstraintValues resolve(ConstraintValues parent, ConstraintValues child) {
		if (parent == null) {
			return child;
		}
		if (child == null) {
			return parent;
		}
		return new ConstraintValues(
				min(parent.maximumPositionCount(), child.maximumPositionCount()),
				min(parent.maximumPositionWeight(), child.maximumPositionWeight()),
				min(parent.maximumSectorWeight(), child.maximumSectorWeight()),
				max(parent.minimumCashWeight(), child.minimumCashWeight()),
				min(parent.maximumLeverageRatio(), child.maximumLeverageRatio()),
				min(parent.maximumSpeculativeWeight(), child.maximumSpeculativeWeight()));
	}

	private static <T extends Comparable<T>> T min(T first, T second) {
		if (first == null) return second;
		if (second == null) return first;
		return first.compareTo(second) <= 0 ? first : second;
	}

	private static <T extends Comparable<T>> T max(T first, T second) {
		if (first == null) return second;
		if (second == null) return first;
		return first.compareTo(second) >= 0 ? first : second;
	}

	private static <T extends Comparable<T>> void requireMaximum(T parent, T child) {
		if (parent != null && child != null && child.compareTo(parent) > 0) {
			throw relaxation();
		}
	}

	private static <T extends Comparable<T>> void requireMinimum(T parent, T child) {
		if (parent != null && child != null && child.compareTo(parent) < 0) {
			throw relaxation();
		}
	}

	private static UserContextException relaxation() {
		return new UserContextException(
				"CONSTRAINT_RELAXATION_NOT_ALLOWED",
				"A more specific policy cannot relax an inherited constraint.",
				422);
	}
}
