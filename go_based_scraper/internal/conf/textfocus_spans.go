// Span finding and scoring for text focus.
package conf

func interestingSpans(text string) [][2]int {
	var hits []int
	for _, m := range datePatterns.FindAllStringIndex(text, -1) {
		hits = append(hits, m[0])
	}
	for _, m := range keywords.FindAllStringIndex(text, -1) {
		hits = append(hits, m[0])
	}
	if len(hits) == 0 {
		return nil
	}
	var spans [][2]int
	for _, h := range hits {
		s := max(0, h-contextChars)
		e := min(len(text), h+contextChars)
		spans = append(spans, [2]int{s, e})
	}
	sortSpans(spans)
	merged := [][2]int{spans[0]}
	for _, s := range spans[1:] {
		last := &merged[len(merged)-1]
		if s[0] <= (*last)[1] {
			(*last)[1] = max((*last)[1], s[1])
		} else {
			merged = append(merged, s)
		}
	}
	return merged
}

func sortSpans(spans [][2]int) {
	for i := 1; i < len(spans); i++ {
		for j := i; j > 0 && spans[j][0] < spans[j-1][0]; j-- {
			spans[j], spans[j-1] = spans[j-1], spans[j]
		}
	}
}
