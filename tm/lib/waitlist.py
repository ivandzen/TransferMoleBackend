from psycopg2.extensions import cursor


class Waitlist:
    @staticmethod
    def append_new(social: str, userid: str, cur: cursor):
        cur.execute(
            f"INSERT INTO public.waitlist(social, userid) "
            f"VALUES(%s, %s)"
            f"ON CONFLICT (social, userid) DO NOTHING;",
            (social, userid,)
        )
