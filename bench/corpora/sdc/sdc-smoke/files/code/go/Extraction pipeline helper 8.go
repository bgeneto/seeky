package main

func extraction_pipeline_helper_8_008Normalize(input string) string {
	fields := strings.Fields(input)
	return strings.ToLower(strings.Join(fields, " "))
}

package main

func extraction_pipeline_helper_8_008Sum(values []int) int {
	total := 0
	for _, value := range values {
		total += value
	}
	return total
}
