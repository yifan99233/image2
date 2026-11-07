const AUTH_INVITE_QUERY_KEYS = ["team_invite_token", "invite_code"] as const;

export const searchWithoutInviteCode = (searchParams: URLSearchParams): string => {
  const nextSearchParams = new URLSearchParams(searchParams);
  nextSearchParams.delete("invite_code");
  return nextSearchParams.toString();
};

export const authPathWithInviteContext = (
  pathname: "/login" | "/register",
  searchParams: URLSearchParams,
): string => {
  const inviteContext = new URLSearchParams();
  for (const key of AUTH_INVITE_QUERY_KEYS) {
    const value = searchParams.get(key)?.trim();
    if (value) {
      inviteContext.set(key, value);
    }
  }

  const query = inviteContext.toString();
  return query ? `${pathname}?${query}` : pathname;
};
