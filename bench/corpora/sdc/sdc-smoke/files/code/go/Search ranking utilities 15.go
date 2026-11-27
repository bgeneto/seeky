package main

func search_ranking_utilities_15_015Sum(values []int) int {
	total := 0
	for _, value := range values {
		total += value
	}
	return total
}

package main

func search_ranking_utilities_15_015Clamp(value, low, high int) int {
	if value < low {
		return low
	}
	if value > high {
		return high
	}
	return value
}

package main

func search_ranking_utilities_15_015Normalize(input string) string {
	fields := strings.Fields(input)
	return strings.ToLower(strings.Join(fields, " "))
}
