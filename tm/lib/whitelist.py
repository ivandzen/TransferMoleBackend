from psycopg2.extensions import cursor


class Whitelist:
    @staticmethod
    def append_new(social: str, userid: str, cur: cursor) -> None:
        cur.execute(
            f"INSERT INTO public.whitelist(social, userid) "
            f"VALUES(%s, %s);",
            (social, userid,)
        )

    @staticmethod
    def is_whitelisted(social: str, userid: str, cur: cursor) -> bool:
        cur.execute(
            f"SELECT social, userid "
            f"FROM public.whitelist "
            f"WHERE social = %s AND userid = %s;",
            (social, userid,)
        )

        result = cur.fetchone()
        return result is not None
