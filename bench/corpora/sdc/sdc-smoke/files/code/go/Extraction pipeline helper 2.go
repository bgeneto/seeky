package main

func extraction_pipeline_helper_2_002Normalize(input string) string {
	fields := strings.Fields(input)
	return strings.ToLower(strings.Join(fields, " "))
}

package main

func extraction_pipeline_helper_2_002Sum(values []int) int {
	total := 0
	for _, value := range values {
		total += value
	}
	return total
}

package main

func extraction_pipeline_helper_2_002Clamp(value, low, high int) int {
	if value < low {
		return low
	}
	if value > high {
		return high
	}
	return value
}
