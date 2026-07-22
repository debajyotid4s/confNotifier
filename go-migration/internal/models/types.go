package models

import "time"

type Conference struct {
	ID                      int        `json:"id"`
	Title                   string     `json:"title"`
	DateStart               *time.Time `json:"date_start,omitempty"`
	DateEnd                 *time.Time `json:"date_end,omitempty"`
	City                    *string    `json:"city,omitempty"`
	Country                 string     `json:"country"`
	Website                 string     `json:"website"`
	Organizer               *string    `json:"organizer,omitempty"`
	Category                *string    `json:"category,omitempty"`
	Confidence              float32    `json:"confidence"`
	SubmissionDeadline      *time.Time `json:"submission_deadline,omitempty"`
	SubmissionDeadlineLabel *string    `json:"submission_deadline_label,omitempty"`
	IsNotified              bool       `json:"is_notified"`
	CreatedAt               time.Time  `json:"created_at"`
	UpdatedAt               time.Time  `json:"updated_at"`
}

type SeenLink struct {
	ID        int       `json:"id"`
	URL       string    `json:"url"`
	Source    string    `json:"source"`
	Status    string    `json:"status"`
	FirstSeen time.Time `json:"first_seen"`
	LastSeen  time.Time `json:"last_seen"`
}

type DomainStrategy struct {
	Domain    string `json:"domain"`
	Strategy  string `json:"strategy"`
	LoadedURL string `json:"loaded_url,omitempty"`
}

type ExtractResult struct {
	IsConference bool    `json:"is_conference"`
	Confidence   float64 `json:"confidence"`
	Title        string  `json:"title,omitempty"`
	DateStart    string  `json:"date_start,omitempty"`
	DateEnd      string  `json:"date_end,omitempty"`
	City         string  `json:"city,omitempty"`
	Organizer    string  `json:"organizer,omitempty"`
	Category     string  `json:"category,omitempty"`
	Deadline     string  `json:"deadline,omitempty"`
	Deadline2    string  `json:"deadline_2,omitempty"`
	DeadlinePrev string  `json:"deadline_previous,omitempty"`
	Deadline2Prev string `json:"deadline_2_previous,omitempty"`
}
