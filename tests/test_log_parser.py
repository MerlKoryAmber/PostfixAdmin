import unittest

from app import parse_log_line, parse_maillog_lines


SAMPLE = [
    'Aug 19 14:20:01 mail postfix/qmgr[100]: ABCDEF1234: from=<alice@src.example>, size=900, nrcpt=1 (queue active)',
    'Aug 19 14:20:02 mail postfix/smtp[200]: ABCDEF1234: to=<bob@dst.example>, relay=mx.dst.example[9.9.9.9]:25, delay=1, dsn=4.4.2, status=deferred (delivery temporarily suspended)',
    'Aug 19 14:20:08 mail postfix/smtp[200]: ABCDEF1234: conversation with mx.dst.example[9.9.9.9] timed out while sending RCPT TO',
    'Aug 19 14:20:09 mail postfix/smtp[201]: connect to other.example[1.1.1.1]:25: Connection timed out',
]


class LogParserTests(unittest.TestCase):
    def test_from_and_to_on_different_lines(self):
        from_line = parse_log_line(SAMPLE[0])
        to_line = parse_log_line(SAMPLE[1])
        self.assertEqual(from_line['from'], 'alice@src.example')
        self.assertEqual(from_line['to'], '')
        self.assertEqual(to_line['from'], '')
        self.assertEqual(to_line['to'], 'bob@dst.example')
        self.assertEqual(to_line['status'], 'deferred')
        self.assertEqual(from_line['queue_id'], 'ABCDEF1234')

    def test_timeout_inherits_from_to_by_qid(self):
        rows = parse_maillog_lines(SAMPLE)
        timeout = rows[2]
        self.assertEqual(timeout['status'], 'timeout')
        self.assertEqual(timeout['from'], 'alice@src.example')
        self.assertEqual(timeout['to'], 'bob@dst.example')
        self.assertEqual(timeout['relay'], 'mx.dst.example')
        self.assertIn('timed out', timeout['raw'])

    def test_timeout_without_qid_stays_empty(self):
        rows = parse_maillog_lines(SAMPLE)
        lone = rows[3]
        self.assertEqual(lone['status'], 'timeout')
        self.assertEqual(lone['from'], '')
        self.assertEqual(lone['to'], '')
        self.assertEqual(lone['relay'], 'other.example')

    def test_empty_from_angle_brackets(self):
        line = 'Aug 19 14:21:00 mail postfix/qmgr[1]: A1B2C3D4E5: from=<>, size=10, nrcpt=1 (queue active)'
        parsed = parse_log_line(line)
        self.assertEqual(parsed['from'], '')
        self.assertEqual(parsed['queue_id'], 'A1B2C3D4E5')


if __name__ == '__main__':
    unittest.main()
