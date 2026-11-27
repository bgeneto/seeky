package main

func extraction_pipeline_helper_7_007Sum(values []int) int {
	total := 0
	for _, value := range values {
		total += value
	}
	return total
}

package main

func extraction_pipeline_helper_7_007Clamp(value, low, high int) int {
	if value < low {
		return low
	}
	if value > high {
		return high
	}
	return value
}
