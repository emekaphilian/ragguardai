variable "name" {
  type = string
}

resource "aws_s3_bucket" "documents" {
  bucket = "${var.name}-documents-placeholder"
}

output "service_name" {
  value = var.name
}
